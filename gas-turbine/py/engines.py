"""
pyCycle engine models used by the Gas Turbine Design Studio.

Two architectures are provided:
  * Turbojet          - single spool: inlet, compressor, burner, turbine, nozzle
  * Turbofan          - two spool, separate flow: fan, LPC, HPC, burner, HPT, LPT,
                        core nozzle and bypass nozzle

Each is wrapped in an MPCycle with one DESIGN point (which sizes the engine) and
one OFF-DESIGN point (which re-uses the sized hardware: map scalars and flow areas).

Tabular air/Jet-A thermodynamics are used so the models solve quickly when run
inside the browser (Pyodide / WebAssembly).
"""
import numpy as np
import openmdao.api as om
import pycycle.api as pyc
from pycycle.thermo.tabular.thermo_add import ThermoAdd as _ThermoAdd

# --------------------------------------------------------------------------- #
#  NumPy >= 2.4 compatibility patch for pyCycle's tabular ThermoAdd
#  (it assigns a size-1 array into a scalar slot, which newer NumPy rejects)
# --------------------------------------------------------------------------- #
_orig_thermo_add_compute = _ThermoAdd.compute


def _thermo_add_compute(self, inputs, outputs):
    if self.options['mix_mode'] != 'reactant':
        return _orig_thermo_add_compute(self, inputs, outputs)
    compo_in = inputs['Fl_I:tot:composition']
    W_in = inputs['Fl_I:stat:W']
    W_air_in = W_in / (1 + np.sum(compo_in))
    W_other_out = np.zeros_like(compo_in) + W_air_in * compo_in
    W_out = 0 + W_in
    W_times_h = W_in * inputs['Fl_I:tot:h']
    for mix_name in self.mix_names:
        W_other_mix = W_air_in * inputs[f'{mix_name}:ratio']
        outputs[f'{mix_name}:W'] = W_other_mix
        W_other_out[self.idx_compo] += W_other_mix.ravel()[0]
        W_out = W_out + W_other_mix
        W_times_h = W_times_h + W_other_mix * inputs[f'{mix_name}:h']
    outputs['composition_out'] = W_other_out / W_air_in
    outputs['Wout'] = W_out
    outputs['mass_avg_h'] = W_times_h / W_out


_ThermoAdd.compute = _thermo_add_compute


def _newton(cycle, maxiter=30, iprint=-1):
    newton = cycle.nonlinear_solver = om.NewtonSolver()
    newton.options['atol'] = 1e-6
    newton.options['rtol'] = 1e-6
    newton.options['iprint'] = iprint
    newton.options['maxiter'] = maxiter
    newton.options['solve_subsystems'] = True
    newton.options['max_sub_solves'] = 100
    newton.options['reraise_child_analysiserror'] = False
    ls = newton.linesearch = om.ArmijoGoldsteinLS()
    ls.options['maxiter'] = 3
    ls.options['rho'] = 0.75
    ls.options['iprint'] = -1
    cycle.linear_solver = om.DirectSolver()


# --------------------------------------------------------------------------- #
#  Turbojet
# --------------------------------------------------------------------------- #
class Turbojet(pyc.Cycle):

    def setup(self):
        design = self.options['design']
        self.options['thermo_method'] = 'TABULAR'
        self.options['thermo_data'] = pyc.AIR_JETA_TAB_SPEC

        self.add_subsystem('fc', pyc.FlightConditions())
        self.add_subsystem('inlet', pyc.Inlet())
        self.add_subsystem('comp', pyc.Compressor(map_data=pyc.AXI5, map_extrap=True),
                           promotes_inputs=['Nmech'])
        self.add_subsystem('burner', pyc.Combustor(fuel_type='FAR'))
        self.add_subsystem('turb', pyc.Turbine(map_data=pyc.LPT2269, map_extrap=True),
                           promotes_inputs=['Nmech'])
        self.add_subsystem('nozz', pyc.Nozzle(nozzType='CV', lossCoef='Cv'))
        self.add_subsystem('shaft', pyc.Shaft(num_ports=2), promotes_inputs=['Nmech'])
        self.add_subsystem('perf', pyc.Performance(num_nozzles=1, num_burners=1))

        self.pyc_connect_flow('fc.Fl_O', 'inlet.Fl_I')
        self.pyc_connect_flow('inlet.Fl_O', 'comp.Fl_I')
        self.pyc_connect_flow('comp.Fl_O', 'burner.Fl_I')
        self.pyc_connect_flow('burner.Fl_O', 'turb.Fl_I')
        self.pyc_connect_flow('turb.Fl_O', 'nozz.Fl_I')

        self.connect('comp.trq', 'shaft.trq_0')
        self.connect('turb.trq', 'shaft.trq_1')
        self.connect('fc.Fl_O:stat:P', 'nozz.Ps_exhaust')

        self.connect('inlet.Fl_O:tot:P', 'perf.Pt2')
        self.connect('comp.Fl_O:tot:P', 'perf.Pt3')
        self.connect('burner.Wfuel', 'perf.Wfuel_0')
        self.connect('inlet.F_ram', 'perf.ram_drag')
        self.connect('nozz.Fg', 'perf.Fg_0')

        balance = self.add_subsystem('balance', om.BalanceComp())
        if design:
            # size the air flow to hit the thrust requirement
            balance.add_balance('W', units='lbm/s', eq_units='lbf', val=50., lower=1., upper=2000.,
                                rhs_name='Fn_target')
            self.connect('balance.W', 'fc.W')
            self.connect('perf.Fn', 'balance.lhs:W')

            balance.add_balance('FAR', eq_units='degR', lower=1e-4, upper=0.06, val=.017,
                                rhs_name='T4_target')
            self.connect('balance.FAR', 'burner.Fl_I:FAR')
            self.connect('burner.Fl_O:tot:T', 'balance.lhs:FAR')

            balance.add_balance('turb_PR', val=3., lower=1.001, upper=12, eq_units='hp', rhs_val=0.)
            self.connect('balance.turb_PR', 'turb.PR')
            self.connect('shaft.pwr_net', 'balance.lhs:turb_PR')
        else:
            # throttle is set by turbine inlet temperature
            balance.add_balance('FAR', eq_units='degR', lower=1e-4, upper=0.06, val=.017,
                                rhs_name='T4_target')
            self.connect('balance.FAR', 'burner.Fl_I:FAR')
            self.connect('burner.Fl_O:tot:T', 'balance.lhs:FAR')

            balance.add_balance('Nmech', val=8000., units='rpm', lower=500., eq_units='hp', rhs_val=0.)
            self.connect('balance.Nmech', 'Nmech')
            self.connect('shaft.pwr_net', 'balance.lhs:Nmech')

            balance.add_balance('W', val=50., units='lbm/s', lower=1., upper=2000., eq_units='inch**2')
            self.connect('balance.W', 'fc.W')
            self.connect('nozz.Throat:stat:area', 'balance.lhs:W')

        _newton(self)
        super().setup()


class MPTurbojet(pyc.MPCycle):

    def initialize(self):
        self.options.declare('with_od', default=True,
                             desc='add an off-design point (False = design point only, faster)')
        super().initialize()

    def setup(self):
        self.pyc_add_pnt('DESIGN', Turbojet(thermo_method='TABULAR'))
        self.set_input_defaults('DESIGN.Nmech', 8070.0, units='rpm')
        self.set_input_defaults('DESIGN.inlet.MN', 0.60)
        self.set_input_defaults('DESIGN.comp.MN', 0.020)
        self.set_input_defaults('DESIGN.burner.MN', 0.020)
        self.set_input_defaults('DESIGN.turb.MN', 0.4)

        self.pyc_add_cycle_param('burner.dPqP', 0.04)
        self.pyc_add_cycle_param('nozz.Cv', 0.99)

        if not self.options['with_od']:
            return super().setup()

        self.pyc_add_pnt('OD', Turbojet(design=False, thermo_method='TABULAR'))
        self.set_input_defaults('OD.fc.MN', 0.0)
        self.set_input_defaults('OD.fc.alt', 0.0, units='ft')
        self.set_input_defaults('OD.fc.dTs', 0.0, units='degR')

        self.pyc_use_default_des_od_conns()
        self.pyc_connect_des_od('nozz.Throat:stat:area', 'balance.rhs:W')
        super().setup()


# --------------------------------------------------------------------------- #
#  Two-spool separate-flow turbofan
# --------------------------------------------------------------------------- #
class Turbofan(pyc.Cycle):

    def setup(self):
        design = self.options['design']
        self.options['thermo_method'] = 'TABULAR'
        self.options['thermo_data'] = pyc.AIR_JETA_TAB_SPEC

        self.add_subsystem('fc', pyc.FlightConditions())
        self.add_subsystem('inlet', pyc.Inlet())
        self.add_subsystem('fan', pyc.Compressor(map_data=pyc.FanMap, map_extrap=True),
                           promotes_inputs=[('Nmech', 'LP_Nmech')])
        self.add_subsystem('splitter', pyc.Splitter())
        self.add_subsystem('duct4', pyc.Duct())
        self.add_subsystem('lpc', pyc.Compressor(map_data=pyc.LPCMap, map_extrap=True),
                           promotes_inputs=[('Nmech', 'LP_Nmech')])
        self.add_subsystem('duct6', pyc.Duct())
        self.add_subsystem('hpc', pyc.Compressor(map_data=pyc.HPCMap, map_extrap=True),
                           promotes_inputs=[('Nmech', 'HP_Nmech')])
        self.add_subsystem('burner', pyc.Combustor(fuel_type='FAR'))
        self.add_subsystem('hpt', pyc.Turbine(map_data=pyc.HPTMap, map_extrap=True),
                           promotes_inputs=[('Nmech', 'HP_Nmech')])
        self.add_subsystem('duct11', pyc.Duct())
        self.add_subsystem('lpt', pyc.Turbine(map_data=pyc.LPTMap, map_extrap=True),
                           promotes_inputs=[('Nmech', 'LP_Nmech')])
        self.add_subsystem('duct13', pyc.Duct())
        self.add_subsystem('core_nozz', pyc.Nozzle(nozzType='CV', lossCoef='Cv'))
        self.add_subsystem('byp_duct', pyc.Duct())
        self.add_subsystem('byp_nozz', pyc.Nozzle(nozzType='CV', lossCoef='Cv'))
        self.add_subsystem('lp_shaft', pyc.Shaft(num_ports=3), promotes_inputs=[('Nmech', 'LP_Nmech')])
        self.add_subsystem('hp_shaft', pyc.Shaft(num_ports=2), promotes_inputs=[('Nmech', 'HP_Nmech')])
        self.add_subsystem('perf', pyc.Performance(num_nozzles=2, num_burners=1))

        self.connect('inlet.Fl_O:tot:P', 'perf.Pt2')
        self.connect('hpc.Fl_O:tot:P', 'perf.Pt3')
        self.connect('burner.Wfuel', 'perf.Wfuel_0')
        self.connect('inlet.F_ram', 'perf.ram_drag')
        self.connect('core_nozz.Fg', 'perf.Fg_0')
        self.connect('byp_nozz.Fg', 'perf.Fg_1')

        self.connect('fan.trq', 'lp_shaft.trq_0')
        self.connect('lpc.trq', 'lp_shaft.trq_1')
        self.connect('lpt.trq', 'lp_shaft.trq_2')
        self.connect('hpc.trq', 'hp_shaft.trq_0')
        self.connect('hpt.trq', 'hp_shaft.trq_1')
        self.connect('fc.Fl_O:stat:P', 'core_nozz.Ps_exhaust')
        self.connect('fc.Fl_O:stat:P', 'byp_nozz.Ps_exhaust')

        self.pyc_connect_flow('fc.Fl_O', 'inlet.Fl_I')
        self.pyc_connect_flow('inlet.Fl_O', 'fan.Fl_I')
        self.pyc_connect_flow('fan.Fl_O', 'splitter.Fl_I')
        self.pyc_connect_flow('splitter.Fl_O1', 'duct4.Fl_I')
        self.pyc_connect_flow('duct4.Fl_O', 'lpc.Fl_I')
        self.pyc_connect_flow('lpc.Fl_O', 'duct6.Fl_I')
        self.pyc_connect_flow('duct6.Fl_O', 'hpc.Fl_I')
        self.pyc_connect_flow('hpc.Fl_O', 'burner.Fl_I')
        self.pyc_connect_flow('burner.Fl_O', 'hpt.Fl_I')
        self.pyc_connect_flow('hpt.Fl_O', 'duct11.Fl_I')
        self.pyc_connect_flow('duct11.Fl_O', 'lpt.Fl_I')
        self.pyc_connect_flow('lpt.Fl_O', 'duct13.Fl_I')
        self.pyc_connect_flow('duct13.Fl_O', 'core_nozz.Fl_I')
        self.pyc_connect_flow('splitter.Fl_O2', 'byp_duct.Fl_I')
        self.pyc_connect_flow('byp_duct.Fl_O', 'byp_nozz.Fl_I')

        balance = self.add_subsystem('balance', om.BalanceComp())
        if design:
            balance.add_balance('W', units='lbm/s', eq_units='lbf', val=100., lower=1., upper=5000.,
                                rhs_name='Fn_target')
            self.connect('balance.W', 'fc.W')
            self.connect('perf.Fn', 'balance.lhs:W')

            balance.add_balance('FAR', eq_units='degR', lower=1e-4, upper=0.06, val=.025,
                                rhs_name='T4_target')
            self.connect('balance.FAR', 'burner.Fl_I:FAR')
            self.connect('burner.Fl_O:tot:T', 'balance.lhs:FAR')

            balance.add_balance('lpt_PR', val=3.0, lower=1.001, upper=20, eq_units='hp', rhs_val=0.)
            self.connect('balance.lpt_PR', 'lpt.PR')
            self.connect('lp_shaft.pwr_net', 'balance.lhs:lpt_PR')

            balance.add_balance('hpt_PR', val=3.0, lower=1.001, upper=12, eq_units='hp', rhs_val=0.)
            self.connect('balance.hpt_PR', 'hpt.PR')
            self.connect('hp_shaft.pwr_net', 'balance.lhs:hpt_PR')
        else:
            balance.add_balance('FAR', eq_units='degR', lower=1e-4, upper=0.06, val=.025,
                                rhs_name='T4_target')
            self.connect('balance.FAR', 'burner.Fl_I:FAR')
            self.connect('burner.Fl_O:tot:T', 'balance.lhs:FAR')

            balance.add_balance('W', units='lbm/s', lower=1., upper=5000., val=100., eq_units='inch**2')
            self.connect('balance.W', 'fc.W')
            self.connect('core_nozz.Throat:stat:area', 'balance.lhs:W')

            balance.add_balance('BPR', lower=0.2, upper=20., val=5., eq_units='inch**2')
            self.connect('balance.BPR', 'splitter.BPR')
            self.connect('byp_nozz.Throat:stat:area', 'balance.lhs:BPR')

            balance.add_balance('lp_Nmech', val=4000., units='rpm', lower=300., eq_units='hp', rhs_val=0.)
            self.connect('balance.lp_Nmech', 'LP_Nmech')
            self.connect('lp_shaft.pwr_net', 'balance.lhs:lp_Nmech')

            balance.add_balance('hp_Nmech', val=14000., units='rpm', lower=1000., eq_units='hp', rhs_val=0.)
            self.connect('balance.hp_Nmech', 'HP_Nmech')
            self.connect('hp_shaft.pwr_net', 'balance.lhs:hp_Nmech')

        _newton(self)
        super().setup()


class MPTurbofan(pyc.MPCycle):

    def initialize(self):
        self.options.declare('with_od', default=True,
                             desc='add an off-design point (False = design point only, faster)')
        super().initialize()

    def setup(self):
        self.pyc_add_pnt('DESIGN', Turbofan(thermo_method='TABULAR'))

        self.set_input_defaults('DESIGN.inlet.MN', 0.62)
        self.set_input_defaults('DESIGN.fan.MN', 0.45)
        self.set_input_defaults('DESIGN.splitter.MN1', 0.30)
        self.set_input_defaults('DESIGN.splitter.MN2', 0.45)
        self.set_input_defaults('DESIGN.duct4.MN', 0.30)
        self.set_input_defaults('DESIGN.lpc.MN', 0.30)
        self.set_input_defaults('DESIGN.duct6.MN', 0.35)
        self.set_input_defaults('DESIGN.hpc.MN', 0.20)
        self.set_input_defaults('DESIGN.burner.MN', 0.10)
        self.set_input_defaults('DESIGN.hpt.MN', 0.30)
        self.set_input_defaults('DESIGN.duct11.MN', 0.35)
        self.set_input_defaults('DESIGN.lpt.MN', 0.40)
        self.set_input_defaults('DESIGN.duct13.MN', 0.40)
        self.set_input_defaults('DESIGN.byp_duct.MN', 0.45)
        self.set_input_defaults('DESIGN.LP_Nmech', 4666.1, units='rpm')
        self.set_input_defaults('DESIGN.HP_Nmech', 14705.7, units='rpm')

        self.pyc_add_cycle_param('duct4.dPqP', 0.0048)
        self.pyc_add_cycle_param('duct6.dPqP', 0.0101)
        self.pyc_add_cycle_param('burner.dPqP', 0.0540)
        self.pyc_add_cycle_param('duct11.dPqP', 0.0051)
        self.pyc_add_cycle_param('duct13.dPqP', 0.0107)
        self.pyc_add_cycle_param('byp_duct.dPqP', 0.0107)
        self.pyc_add_cycle_param('core_nozz.Cv', 0.9933)
        self.pyc_add_cycle_param('byp_nozz.Cv', 0.9939)
        self.pyc_add_cycle_param('lp_shaft.HPX', 0.0, units='hp')
        self.pyc_add_cycle_param('hp_shaft.HPX', 250.0, units='hp')

        if not self.options['with_od']:
            return super().setup()

        self.pyc_add_pnt('OD', Turbofan(design=False, thermo_method='TABULAR'))
        self.set_input_defaults('OD.fc.MN', 0.0)
        self.set_input_defaults('OD.fc.alt', 0.0, units='ft')
        self.set_input_defaults('OD.fc.dTs', 0.0, units='degR')

        self.pyc_use_default_des_od_conns()
        self.pyc_connect_des_od('core_nozz.Throat:stat:area', 'balance.rhs:W')
        self.pyc_connect_des_od('byp_nozz.Throat:stat:area', 'balance.rhs:BPR')
        super().setup()
