"""
Gas Turbine Design Studio - Python API called from the browser (via Pyodide).

All inputs and outputs use pyCycle's native (US customary) units:
  altitude ft, temperatures degR, pressures psia, flow lbm/s, thrust lbf,
  TSFC lbm/(hr*lbf), areas in^2, power hp, speed rpm.
The JavaScript front end converts to SI for display when requested.

Every public function takes and returns plain JSON strings so the JS side
never has to deal with Python proxies.
"""
import json
import math
import numpy as np
import openmdao.api as om
from openmdao.core.analysis_error import AnalysisError

import pycycle.api as pyc
from engines import MPTurbojet, MPTurbofan

# --------------------------------------------------------------------------- #
#  Constants / helpers
# --------------------------------------------------------------------------- #
LBF2N = 4.4482216
LBM2KG = 0.45359237
FT2M = 0.3048
IN2M = 0.0254
DEBUG = False
LHV_JETA = 43.2e6          # J/kg, lower heating value used for efficiency bookkeeping


def isa(alt_ft, dTs=0.0):
    """Standard atmosphere (to 65 kft). Returns static T (degR) and P (psia)."""
    h = alt_ft * FT2M
    if h <= 11000.0:
        T = 288.15 - 0.0065 * h
        P = 101325.0 * (T / 288.15) ** 5.25588
    else:
        T = 216.65
        P = 22632.06 * math.exp(-(h - 11000.0) / 6341.62)
    return T * 1.8 + dTs, P / 6894.757


def total_guess(alt_ft, MN, dTs=0.0):
    Ts, Ps = isa(alt_ft, dTs)
    g = 1.4
    f = 1 + 0.5 * (g - 1) * MN ** 2
    return Ts * f, Ps * f ** (g / (g - 1))


def _f(x):
    v = float(np.asarray(x).ravel()[0])
    if not math.isfinite(v):
        raise AnalysisError('non-finite result')
    return v


# --------------------------------------------------------------------------- #
#  Architecture definitions
# --------------------------------------------------------------------------- #
ARCH = {
    'turbojet': {
        'cls': MPTurbojet,
        'compressors': [('comp', 'Compressor', 'AXI5')],
        'turbines': [('turb', 'Turbine')],
        'nozzles': [('nozz', 'Nozzle')],
        'shafts': [('shaft', 'Nmech', 'Shaft')],
        'fan_face': ('inlet', 0.40),
        'stations': [
            ('0', 'fc.Fl_O', 'Freestream'),
            ('2', 'inlet.Fl_O', 'Compressor face'),
            ('3', 'comp.Fl_O', 'Compressor exit'),
            ('4', 'burner.Fl_O', 'Turbine inlet'),
            ('5', 'turb.Fl_O', 'Turbine exit'),
            ('9', 'nozz.Fl_O', 'Nozzle exit'),
        ],
        'ts_path': ['0', '2', '3', '4', '5', '9'],
    },
    'turbofan': {
        'cls': MPTurbofan,
        'compressors': [('fan', 'Fan', 'FanMap'), ('lpc', 'LP compressor (booster)', 'LPCMap'),
                        ('hpc', 'HP compressor', 'HPCMap')],
        'turbines': [('hpt', 'HP turbine'), ('lpt', 'LP turbine')],
        'nozzles': [('core_nozz', 'Core nozzle'), ('byp_nozz', 'Bypass nozzle')],
        'shafts': [('lp_shaft', 'LP_Nmech', 'LP spool'), ('hp_shaft', 'HP_Nmech', 'HP spool')],
        'fan_face': ('inlet', 0.30),
        'stations': [
            ('0', 'fc.Fl_O', 'Freestream'),
            ('2', 'inlet.Fl_O', 'Fan face'),
            ('21', 'fan.Fl_O', 'Fan exit'),
            ('13', 'splitter.Fl_O2', 'Bypass duct entry'),
            ('19', 'byp_nozz.Fl_O', 'Bypass nozzle exit'),
            ('22', 'splitter.Fl_O1', 'Core entry'),
            ('24', 'lpc.Fl_O', 'LPC exit'),
            ('25', 'duct6.Fl_O', 'HPC inlet'),
            ('3', 'hpc.Fl_O', 'HPC exit'),
            ('4', 'burner.Fl_O', 'HPT inlet'),
            ('45', 'duct11.Fl_O', 'LPT inlet'),
            ('5', 'lpt.Fl_O', 'LPT exit'),
            ('9', 'core_nozz.Fl_O', 'Core nozzle exit'),
        ],
        'ts_path': ['0', '2', '22', '24', '25', '3', '4', '45', '5', '9'],
        'ts_bypass': ['2', '21', '13', '19'],
    },
}

MAPS = {'AXI5': pyc.AXI5, 'FanMap': pyc.FanMap, 'LPCMap': pyc.LPCMap, 'HPCMap': pyc.HPCMap}

# default solver guesses per architecture (design point, off-design point)
GUESS = {
    'turbojet': {
        'DESIGN': {'balance.FAR': 0.0175, 'balance.W': 100., 'balance.turb_PR': 4.0},
        'OD': {'balance.FAR': 0.017, 'balance.W': 100., 'balance.Nmech': 8000.},
    },
    'turbofan': {
        'DESIGN': {'balance.FAR': 0.025, 'balance.W': 100., 'balance.lpt_PR': 4.0, 'balance.hpt_PR': 3.0},
        'OD': {'balance.FAR': 0.025, 'balance.W': 250., 'balance.BPR': 5.0,
               'balance.lp_Nmech': 4666., 'balance.hp_Nmech': 14705.},
    },
}


# --------------------------------------------------------------------------- #
#  Problem cache (one problem per architecture: DESIGN + one OD point)
# --------------------------------------------------------------------------- #
class Engine:

    def __init__(self, arch, with_od):
        self.arch = arch
        self.cfg = ARCH[arch]
        self.with_od = with_od
        self.points = ('DESIGN', 'OD') if with_od else ('DESIGN',)
        p = self.prob = om.Problem(reports=False)
        p.model = self.cfg['cls'](with_od=with_od)
        p.setup(check=False)
        p.set_solver_print(level=-1)
        # make the top-level cycle solvers raise on non-convergence so we can
        # report failures instead of silently returning garbage
        for pt in self.points:
            sub = p.model._get_subsystem(pt)
            sub.nonlinear_solver.options['err_on_non_converge'] = True
        p.final_setup()
        self.init_state = self._snapshot()   # clean state, used before every cold start
        self.good_state = None      # snapshot of all outputs after last converged run
        self.good_design = None     # design inputs of that snapshot
        self.good_od = None         # off-design condition of that snapshot
        self.design_inputs = None   # inputs used for the current design
        self.seed = None
        self.seed_design = None

    # ---- state management ------------------------------------------------ #
    def _snapshot(self):
        return self.prob.model._outputs.asarray().copy()

    def _restore(self, snap):
        self.prob.model._outputs.set_val(snap)

    def _apply_guesses(self, pt):
        for k, v in GUESS[self.arch][pt].items():
            self.prob.set_val(f'{pt}.{k}', v)

    # ---- input setting --------------------------------------------------- #
    def set_design(self, d):
        p = self.prob
        D = 'DESIGN.'
        alt = d['alt']
        MN = max(d['MN'], 1e-4)
        dTs = d.get('dTs', 0.0)
        p.set_val(D + 'fc.alt', alt, units='ft')
        p.set_val(D + 'fc.MN', MN)
        p.set_val(D + 'fc.dTs', dTs, units='degR')
        p.set_val(D + 'balance.Fn_target', d['Fn'], units='lbf')
        p.set_val(D + 'balance.T4_target', d['T4'], units='degR')
        p.set_val(D + 'inlet.ram_recovery', d.get('ram_recovery', 0.995))
        p.set_val('burner.dPqP', d.get('burner_dPqP', 0.04))
        Tt, Pt = total_guess(alt, MN, dTs)
        p.set_val(D + 'fc.balance.Tt', Tt)
        p.set_val(D + 'fc.balance.Pt', Pt)
        # where each compressor's design point sits on its map (R-line; 1 = surge line)
        for c, _, mapname in self.cfg['compressors']:
            p.set_val(f'{D}{c}.map.RlineMap', d.get(f'Rline_{c}', MAPS[mapname].defaults['RlineMap']))

        if self.arch == 'turbojet':
            p.set_val(D + 'comp.PR', d['OPR'])
            p.set_val(D + 'comp.eff', d['comp_eff'])
            p.set_val(D + 'turb.eff', d['turb_eff'])
            p.set_val('nozz.Cv', d.get('Cv', 0.99))
        else:
            fpr, lpc = d['FPR'], d['LPC_PR']
            hpc = d['OPR'] / (fpr * lpc)
            if hpc < 1.2:
                raise AnalysisError(f'OPR too low for chosen fan/booster pressure ratios (HPC PR = {hpc:.2f})')
            p.set_val(D + 'fan.PR', fpr)
            p.set_val(D + 'lpc.PR', lpc)
            p.set_val(D + 'hpc.PR', hpc)
            p.set_val(D + 'fan.eff', d['fan_eff'])
            p.set_val(D + 'lpc.eff', d['lpc_eff'])
            p.set_val(D + 'hpc.eff', d['hpc_eff'])
            p.set_val(D + 'hpt.eff', d['hpt_eff'])
            p.set_val(D + 'lpt.eff', d['lpt_eff'])
            p.set_val(D + 'splitter.BPR', d['BPR'])
            p.set_val('core_nozz.Cv', d.get('Cv', 0.9933))
            p.set_val('byp_nozz.Cv', d.get('Cv', 0.9939))
            p.set_val('hp_shaft.HPX', d.get('HPX', 250.), units='hp')

    def set_od(self, o):
        p = self.prob
        O = 'OD.'
        alt = o['alt']
        MN = max(o['MN'], 1e-4)
        dTs = o.get('dTs', 0.0)
        p.set_val(O + 'fc.alt', alt, units='ft')
        p.set_val(O + 'fc.MN', MN)
        p.set_val(O + 'fc.dTs', dTs, units='degR')
        p.set_val(O + 'balance.T4_target', o['T4'], units='degR')
        p.set_val(O + 'inlet.ram_recovery', o.get('ram_recovery', 0.995))
        Tt, Pt = total_guess(alt, MN, dTs)
        p.set_val(O + 'fc.balance.Tt', Tt)
        p.set_val(O + 'fc.balance.Pt', Pt)

    # ---- solving -------------------------------------------------------- #
    def _design_seed(self, design):
        """Initial guesses for the design point, scaled to the thrust requirement."""
        if self.arch == 'turbojet':
            fsp = 80.0
        else:
            fsp = 60.0 / (1.0 + design['BPR']) ** 0.55
        g = dict(GUESS[self.arch]['DESIGN'])
        g['balance.W'] = max(1.0, design['Fn'] / fsp)
        return g

    def _od_seed(self, ref, od, vals=None):
        """Off-design guesses scaled from a converged reference condition `ref` with
        balance values `vals` (default: the design solution), assuming constant corrected
        flow and corrected speed (a good first-order estimate)."""
        vals = vals or self.seed
        Tt_r, Pt_r = total_guess(ref['alt'], max(ref['MN'], 1e-4), ref.get('dTs', 0.))
        Tt_o, Pt_o = total_guess(od['alt'], max(od['MN'], 1e-4), od.get('dTs', 0.))
        th = math.sqrt(Tt_o / Tt_r)
        g = {'balance.W': vals['W'] * (Pt_o / Pt_r) / th,
             'balance.FAR': vals['FAR'] * od['T4'] / ref['T4']}
        if self.arch == 'turbojet':
            g['balance.Nmech'] = vals['N'] * th
        else:
            g['balance.BPR'] = vals['BPR']
            g['balance.lp_Nmech'] = vals['LP_N'] * th
            g['balance.hp_Nmech'] = vals['HP_N'] * th
        return g

    def _od_vals(self):
        """Current OD balance values (after restoring a converged snapshot)."""
        g = self.g
        v = {'W': g('OD.balance.W'), 'FAR': g('OD.balance.FAR')}
        if self.arch == 'turbojet':
            v['N'] = g('OD.balance.Nmech')
        else:
            v.update(BPR=g('OD.balance.BPR'), LP_N=g('OD.balance.lp_Nmech'), HP_N=g('OD.balance.hp_Nmech'))
        return v

    def _solve_design_only(self, design):
        """Solve the design point on the (cheap) design-only engine to seed guesses."""
        e = self if not self.with_od else _engine(self.arch, with_od=False)
        if e is not self:
            e.run(design)
        g = e.g
        seed = {'W': g('DESIGN.balance.W'), 'FAR': g('DESIGN.balance.FAR')}
        if self.arch == 'turbojet':
            seed.update(N=g('DESIGN.Nmech', 'rpm'), turb_PR=g('DESIGN.balance.turb_PR'))
        else:
            seed.update(BPR=design['BPR'], LP_N=g('DESIGN.LP_Nmech', 'rpm'), HP_N=g('DESIGN.HP_Nmech', 'rpm'),
                        lpt_PR=g('DESIGN.balance.lpt_PR'), hpt_PR=g('DESIGN.balance.hpt_PR'))
        self.seed = seed
        self.seed_design = dict(design)

    def _attempt(self, design, od, prep):
        prep()
        self.set_design(design)
        if self.with_od:
            self.set_od(od)
        self.prob.run_model()
        self._check()
        self.good_state = self._snapshot()
        self.good_design = dict(design)
        self.good_od = dict(od) if od else None
        self.design_inputs = dict(design)

    def _continuation(self, design, od, start_od, n=4):
        """March the off-design condition from a converged state towards the target."""
        for k in range(1, n + 1):
            f = k / n
            mid = {key: start_od[key] + f * (od[key] - start_od[key]) for key in ('alt', 'MN', 'dTs', 'T4')}
            mid['ram_recovery'] = od.get('ram_recovery', 0.995)
            self.set_od(mid)
            self.set_design(design)
            self.prob.run_model()
            self._check()
        self.good_state = self._snapshot()
        self.good_design = dict(design)
        self.good_od = dict(od)
        self.design_inputs = dict(design)

    def run(self, design, od=None):
        """Run the model. If od is None, the off-design point (if any) re-uses the design
        flight condition. Several strategies are tried, cheapest first."""
        if od is None:
            od = dict(alt=design['alt'], MN=design['MN'], dTs=design.get('dTs', 0.),
                      T4=design['T4'], ram_recovery=design.get('ram_recovery', 0.995))
        od = {k: float(od.get(k, 0.0)) for k in ('alt', 'MN', 'dTs', 'T4')} | \
             {'ram_recovery': float(od.get('ram_recovery', 0.995))}
        des_od = dict(alt=design['alt'], MN=design['MN'], dTs=design.get('dTs', 0.),
                      T4=design['T4'], ram_recovery=design.get('ram_recovery', 0.995))
        strategies = []
        snap = self.good_state
        same_design = snap is not None and self.good_design == design

        def warm():
            self._restore(snap)
            if self.with_od and self.good_od and self.good_od != od:
                for k, v in self._od_seed(self.good_od, od, self._od_vals()).items():
                    self.prob.set_val('OD.' + k, v)
        if snap is not None:
            strategies.append(('warm start', lambda: self._attempt(design, od, warm)))

        if self.with_od:
            if same_design and self.good_od and self.good_od != od:
                prev = dict(self.good_od)
                strategies.append(('continuation', lambda: (self._restore(snap), self._continuation(design, od, prev))))

            def seeded_prep(target):
                self._restore(self.init_state)
                self._apply_guesses('DESIGN')
                for k, v in (('W', 'balance.W'), ('FAR', 'balance.FAR')):
                    self.prob.set_val('DESIGN.' + v, self.seed[k])
                if self.arch == 'turbojet':
                    self.prob.set_val('DESIGN.balance.turb_PR', self.seed['turb_PR'])
                else:
                    self.prob.set_val('DESIGN.balance.lpt_PR', self.seed['lpt_PR'])
                    self.prob.set_val('DESIGN.balance.hpt_PR', self.seed['hpt_PR'])
                self._apply_guesses('OD')
                for k, v in self._od_seed(des_od, target).items():
                    self.prob.set_val('OD.' + k, v)

            def cold():
                self._solve_design_only(design)
                self._attempt(design, od, lambda: seeded_prep(od))
            strategies.append(('seeded cold start', cold))

            def cold_cont():
                # solve at the design condition first, then march to the target
                if self.seed_design != design:
                    self._solve_design_only(design)
                self._attempt(design, des_od, lambda: seeded_prep(des_od))
                self._continuation(design, od, des_od, n=5)
            if od != des_od:
                strategies.append(('cold continuation', cold_cont))
        else:
            def cold():
                self._restore(self.init_state)
                self._apply_guesses('DESIGN')
                for k, v in self._design_seed(design).items():
                    self.prob.set_val('DESIGN.' + k, v)
            strategies.append(('cold start', lambda: self._attempt(design, od, cold)))

        last_err = None
        for name, strat in strategies:
            try:
                strat()
                self.last_strategy = name
                return True
            except Exception as e:  # AnalysisError or numerical blow-ups inside components
                last_err = e
                if DEBUG:
                    print(f'##   strategy {name} failed: {str(e).splitlines()[0][:160]}')
        self.good_state = snap
        raise AnalysisError(f'Solver did not converge: {str(last_err).splitlines()[0][:200]}')

    def run_od_only(self, od):
        """Re-run with the current design inputs but a new off-design condition."""
        if self.design_inputs is None:
            raise AnalysisError('Run the design point first.')
        return self.run(self.design_inputs, od)

    def _check(self):
        for pt in self.points:
            _f(self.prob.get_val(f'{pt}.perf.Fn'))
            _f(self.prob.get_val(f'{pt}.perf.TSFC'))

    # ---- results extraction --------------------------------------------- #
    def g(self, name, units=None):
        return _f(self.prob.get_val(name, units=units) if units else self.prob.get_val(name))

    def stations(self, pt):
        out = []
        for sid, path, desc in self.cfg['stations']:
            P = f'{pt}.{path}'
            row = {'id': sid, 'name': desc}
            try:
                row['W'] = self.g(P + ':stat:W', 'lbm/s')
            except Exception:
                row['W'] = None
            for key, var, u in (('Tt', ':tot:T', 'degR'), ('Pt', ':tot:P', 'psi'),
                                ('ht', ':tot:h', 'Btu/lbm'), ('S', ':tot:S', 'Btu/(lbm*degR)'),
                                ('Ts', ':stat:T', 'degR'), ('Ps', ':stat:P', 'psi'),
                                ('MN', ':stat:MN', None), ('V', ':stat:V', 'ft/s'),
                                ('A', ':stat:area', 'inch**2')):
                try:
                    row[key] = self.g(P + var, u)
                except Exception:
                    row[key] = None
            out.append(row)
        return out

    def performance(self, pt):
        g = self.g
        r = {
            'alt': g(f'{pt}.fc.alt', 'ft'), 'MN': g(f'{pt}.fc.MN'),
            'Fn': g(f'{pt}.perf.Fn', 'lbf'), 'Fg': g(f'{pt}.perf.Fg', 'lbf'),
            'ram_drag': g(f'{pt}.inlet.F_ram', 'lbf'),
            'TSFC': g(f'{pt}.perf.TSFC', 'lbm/(h*lbf)'), 'OPR': g(f'{pt}.perf.OPR'),
            'Wfuel': g(f'{pt}.perf.Wfuel', 'lbm/s'), 'W': g(f'{pt}.inlet.Fl_O:stat:W', 'lbm/s'),
            'FAR': g(f'{pt}.balance.FAR'),
            'T4': g(f'{pt}.burner.Fl_O:tot:T', 'degR'),
            'T3': g(f'{pt}.{"comp" if self.arch == "turbojet" else "hpc"}.Fl_O:tot:T', 'degR'),
            'P3': g(f'{pt}.{"comp" if self.arch == "turbojet" else "hpc"}.Fl_O:tot:P', 'psi'),
        }
        r['Fsp'] = r['Fn'] / r['W']           # lbf/(lbm/s)
        V0 = g(f'{pt}.fc.Fl_O:stat:V', 'ft/s')
        r['V0'] = V0
        if self.arch == 'turbofan':
            r['BPR'] = g(f'{pt}.splitter.BPR')

        # efficiency bookkeeping (SI) using effective jet velocities Fg/W
        W0 = r['W'] * LBM2KG
        V0s = V0 * FT2M
        ke_jet = 0.0
        for nz, _ in self.cfg['nozzles']:
            Wn = g(f'{pt}.{nz}.Fl_O:stat:W', 'lbm/s') * LBM2KG
            Fgn = g(f'{pt}.{nz}.Fg', 'lbf') * LBF2N
            if Wn > 0:
                ke_jet += 0.5 * Fgn ** 2 / Wn
        dKE = ke_jet - 0.5 * W0 * V0s ** 2
        Q = r['Wfuel'] * LBM2KG * LHV_JETA
        r['eta_th'] = dKE / Q if Q > 0 else None
        r['eta_prop'] = (r['Fn'] * LBF2N * V0s / dKE) if (dKE > 0 and V0s > 1) else None
        r['eta_overall'] = (r['Fn'] * LBF2N * V0s / Q) if (Q > 0 and V0s > 1) else None

        # components
        comps = []
        for c, label, _ in self.cfg['compressors']:
            comps.append({
                'key': c, 'name': label,
                'PR': g(f'{pt}.{c}.PR'), 'eff': g(f'{pt}.{c}.eff'),
                'Wc': g(f'{pt}.{c}.Wc', 'lbm/s'), 'Nc': g(f'{pt}.{c}.Nc', 'rpm'),
                'power': -g(f'{pt}.{c}.power', 'hp'),
                'SMN': g(f'{pt}.{c}.SMN'), 'SMW': g(f'{pt}.{c}.SMW'),
                'Rline': g(f'{pt}.{c}.map.RlineMap'), 'NcMap': g(f'{pt}.{c}.map.NcMap'),
            })
        r['compressors'] = comps
        turbs = []
        for t, label in self.cfg['turbines']:
            turbs.append({'key': t, 'name': label, 'PR': g(f'{pt}.{t}.PR'), 'eff': g(f'{pt}.{t}.eff'),
                          'power': g(f'{pt}.{t}.power', 'hp')})
        r['turbines'] = turbs
        shafts = []
        for s, nm, label in self.cfg['shafts']:
            shafts.append({'key': s, 'name': label, 'N': g(f'{pt}.{nm}', 'rpm')})
        r['shafts'] = shafts
        nozz = []
        for nz, label in self.cfg['nozzles']:
            nozz.append({'key': nz, 'name': label, 'Fg': g(f'{pt}.{nz}.Fg', 'lbf'),
                         'W': g(f'{pt}.{nz}.Fl_O:stat:W', 'lbm/s'),
                         'V': g(f'{pt}.{nz}.Fl_O:stat:V', 'ft/s'),
                         'MN': g(f'{pt}.{nz}.Fl_O:stat:MN'),
                         'A_throat': g(f'{pt}.{nz}.Throat:stat:area', 'inch**2'),
                         'PR': g(f'{pt}.{nz}.PR')})
        r['nozzles'] = nozz
        return r

    def sizing(self):
        key, htr = self.cfg['fan_face']
        A = self.g(f'DESIGN.{key}.Fl_O:stat:area', 'inch**2')
        D = math.sqrt(4 * A / (math.pi * (1 - htr ** 2)))
        return {'fan_face_area': A, 'fan_diameter': D, 'hub_tip': htr}

    def maps(self):
        """Scaled compressor maps (speed lines, surge line) for the current design."""
        out = []
        for c, label, mapname in self.cfg['compressors']:
            md = MAPS[mapname]
            s_Wc = self.g(f'DESIGN.{c}.s_Wc')
            s_PR = self.g(f'DESIGN.{c}.s_PR')
            s_eff = self.g(f'DESIGN.{c}.s_eff')
            Nc_des = md.defaults['NcMap']
            Wc = np.asarray(md.WcMap)[0] * s_Wc
            PR = (np.asarray(md.PRmap)[0] - 1.0) * s_PR + 1.0
            eff = np.asarray(md.effMap)[0] * s_eff
            lines = []
            for i, nc in enumerate(md.NcMap):
                lines.append({'N': float(nc / Nc_des), 'Wc': Wc[i].tolist(), 'PR': PR[i].tolist(),
                              'eff': eff[i].tolist()})
            surge = {'Wc': Wc[:, 0].tolist(), 'PR': PR[:, 0].tolist()}
            out.append({'key': c, 'name': label, 'lines': lines, 'surge': surge,
                        'design': {'Wc': self.g(f'DESIGN.{c}.Wc', 'lbm/s'), 'PR': self.g(f'DESIGN.{c}.PR')}})
        return out


_ENGINES = {}


def _engine(arch, with_od=True):
    key = (arch, with_od)
    if key not in _ENGINES:
        _ENGINES[key] = Engine(arch, with_od)
    return _ENGINES[key]


def _decode(a):
    if isinstance(a, str) and a[:1] in '{["':
        return json.loads(a)
    return a


def _wrap(fn):
    def inner(*args):
        try:
            return json.dumps({'ok': True, 'data': fn(*[_decode(a) for a in args])})
        except AnalysisError as e:
            return json.dumps({'ok': False, 'error': str(e)})
        except Exception as e:
            return json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'})
    return inner


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
@_wrap
def build(arch, with_od=True):
    _engine(arch, with_od)
    return {'arch': arch}


@_wrap
def design_point(arch, design):
    """Quick design-point evaluation (used for trade studies, no off-design point)."""
    e = _engine(arch, with_od=False)
    e.run(design)
    perf = e.performance('DESIGN')
    return {'perf': perf, 'sizing': e.sizing()}


@_wrap
def design_full(arch, design):
    """Full design-point report: performance, stations, sizing and scaled maps."""
    e = _engine(arch)
    e.run(design)
    return {
        'perf': e.performance('DESIGN'),
        'stations': e.stations('DESIGN'),
        'sizing': e.sizing(),
        'maps': e.maps(),
        'ts_path': e.cfg['ts_path'],
        'ts_bypass': e.cfg.get('ts_bypass'),
    }


@_wrap
def off_design(arch, design, od):
    """Evaluate the sized engine at an off-design condition (T4 sets the throttle)."""
    e = _engine(arch)
    if e.design_inputs != design:
        e.run(design)
    e.run_od_only(od)
    return {'perf': e.performance('OD'), 'stations': e.stations('OD')}


@_wrap
def atmosphere(alt, dTs):
    Ts, Ps = isa(alt, dTs)
    return {'Ts': Ts, 'Ps': Ps}
