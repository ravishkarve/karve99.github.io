/* Page 1: tutorials. Lessons, interactive widgets and quizzes. */
(function () {
  'use strict';
  const { bs, fmt, esc, store, css, payoffChart, payoffStats, positionPnl } = OD;
  const LOT = 75; // example lot size used throughout the lessons

  // ---------------------------------------------------------------- lessons
  const LESSONS = [
    {
      id: 'basics', title: 'Shares, indices and derivatives',
      html: `
<div class="eyebrow">Lesson 1</div>
<h1>Shares, indices and derivatives</h1>
<p>Before options make sense you need three ideas: a <b>share</b>, an <b>index</b> and a <b>derivative</b>.</p>
<h2>Shares</h2>
<p>A share is a small slice of ownership in a company. If you own one share of a company and the share price goes from ₹1,000 to ₹1,100, you have made ₹100. If it falls to ₹900 you have lost ₹100. Simple: you make money when the price goes up.</p>
<h2>Indices</h2>
<p>An index is a basket of shares tracked as a single number. The <b>NIFTY 50</b> follows 50 of the largest companies on India's National Stock Exchange (NSE). The <b>BANK NIFTY</b> follows the biggest banks. When people say "the market went up 1% today" they usually mean NIFTY went up 1%.</p>
<p>You cannot buy "one NIFTY" directly like a share, but you can trade <b>derivatives</b> whose value depends on it. Most options trading in India happens on NIFTY and BANK NIFTY.</p>
<h2>Derivatives</h2>
<p>A derivative is a contract whose value is <i>derived</i> from something else, called the <b>underlying</b>. The two you will meet are:</p>
<ul>
  <li><b>Futures</b>: an agreement to buy or sell the underlying at a fixed price on a future date. Both sides are obligated.</li>
  <li><b>Options</b>: a contract that gives the buyer a <i>right, but not an obligation</i>, to buy or sell at a fixed price. This one-sidedness is what makes options special, and it is the rest of this course.</li>
</ul>
<div class="callout"><p><b>Everyday analogy.</b> You pay a builder a ₹50,000 non-refundable booking amount to lock in a flat at ₹80 lakh for three months. If prices in the area jump to ₹95 lakh, you exercise your right and buy at ₹80 lakh. If prices fall, you walk away and lose only the ₹50,000. That booking amount is an option premium.</p></div>
<h2>Contracts come in lots</h2>
<p>Exchange-traded options are sold in fixed bundles called <b>lots</b>. A NIFTY option might have a lot size of ${LOT} units (NSE revises lot sizes from time to time, so always check the current figure). If an option's price is ₹100, one lot costs ₹100 × ${LOT} = ₹${(100 * LOT).toLocaleString('en-IN')}. Every rupee move in the option price changes your P&amp;L by ₹${LOT} per lot.</p>`,
      quiz: [
        { q: 'What is the NIFTY 50?', opts: ['A single company', 'A basket of 50 large NSE-listed companies tracked as one number', 'A type of option', 'A government bond'], a: 1, why: 'NIFTY 50 is an index: a weighted basket of 50 large companies, quoted as a single number.' },
        { q: 'What makes an option different from a future?', opts: ['Options never expire', 'The option buyer has a right but no obligation', 'Futures cannot lose money', 'Options only work on shares'], a: 1, why: 'A futures contract binds both sides. An option buyer can simply walk away; only the seller is obligated.' },
        { q: `An option is priced at ₹40 and the lot size is ${LOT}. What does one lot cost?`, opts: ['₹40', `₹${40 * LOT}`, '₹4,000', '₹75'], a: 1, why: `Premium × lot size = 40 × ${LOT} = ₹${(40 * LOT).toLocaleString('en-IN')}.` },
      ],
    },
    {
      id: 'calls', title: 'Call options',
      html: `
<div class="eyebrow">Lesson 2</div>
<h1>Call options: the right to buy</h1>
<p>A <b>call option</b> gives the buyer the right to <b>buy</b> the underlying at a fixed price, the <b>strike price</b>, on or before the <b>expiry date</b>. The buyer pays the seller a <b>premium</b> for this right.</p>
<h2>A worked example</h2>
<p>NIFTY is at 25,000. You think it will rise. You buy one NIFTY <b>25,000 call</b> expiring next week for a premium of ₹150.</p>
<ul>
  <li>You pay 150 × ${LOT} = <b>₹${(150 * LOT).toLocaleString('en-IN')}</b>. That is the most you can lose.</li>
  <li>If NIFTY ends at 25,400 at expiry, the call is worth 25,400 − 25,000 = 400. Your profit is (400 − 150) × ${LOT} = <b>₹${(250 * LOT).toLocaleString('en-IN')}</b>.</li>
  <li>If NIFTY ends at 24,800, the right to buy at 25,000 is worthless. You lose the ₹${(150 * LOT).toLocaleString('en-IN')} premium, no more.</li>
  <li>Your <b>breakeven</b> is strike + premium = 25,150. Above that you profit.</li>
</ul>
<p>Drag the slider to see the P&amp;L for any closing price. Then flip to <b>Sell</b>: the seller's chart is the exact mirror image. The seller keeps the premium if NIFTY stays below the strike, but faces <b>unlimited</b> losses if it rallies hard.</p>
<div class="widget" data-widget="payoff" data-type="C"></div>
<div class="callout warn"><p><b>Buyer vs seller.</b> Buyers risk a small, known amount for a large, uncertain gain. Sellers collect a small, certain premium and take on a large, uncertain risk. Every trade has one of each.</p></div>`,
      quiz: [
        { q: 'You buy a 25,000 call for ₹150. NIFTY expires at 25,100. What is your P&L per unit?', opts: ['+₹100', '−₹50', '+₹250', '−₹150'], a: 1, why: 'The call is worth 100 at expiry (25,100 − 25,000). You paid 150, so you are down 50 per unit.' },
        { q: 'What is the maximum loss for a call buyer?', opts: ['Unlimited', 'The strike price', 'The premium paid', 'Zero'], a: 2, why: 'A buyer can always walk away, so the worst case is losing the premium.' },
        { q: 'Who faces unlimited risk on a call?', opts: ['The buyer', 'The seller (writer)', 'The exchange', 'Nobody'], a: 1, why: 'If the price keeps rising, the seller must keep paying out the difference with no cap.' },
      ],
    },
    {
      id: 'puts', title: 'Put options',
      html: `
<div class="eyebrow">Lesson 3</div>
<h1>Put options: the right to sell</h1>
<p>A <b>put option</b> gives the buyer the right to <b>sell</b> the underlying at the strike price. Puts gain value when the market <b>falls</b>. They work like insurance: you pay a premium to protect yourself against a drop.</p>
<h2>A worked example</h2>
<p>NIFTY is at 25,000. You buy one <b>24,900 put</b> for ₹110.</p>
<ul>
  <li>Cost: 110 × ${LOT} = <b>₹${(110 * LOT).toLocaleString('en-IN')}</b>, your maximum loss.</li>
  <li>If NIFTY crashes to 24,300, the put is worth 24,900 − 24,300 = 600. Profit: (600 − 110) × ${LOT} = <b>₹${(490 * LOT).toLocaleString('en-IN')}</b>.</li>
  <li>If NIFTY stays above 24,900, the put expires worthless.</li>
  <li>Breakeven = strike − premium = 24,790.</li>
</ul>
<div class="widget" data-widget="payoff" data-type="P"></div>
<h2>The four basic positions</h2>
<div class="table-wrap"><table class="data">
<thead><tr><th class="text">Position</th><th class="text">Your view</th><th class="text">Max profit</th><th class="text">Max loss</th></tr></thead>
<tbody>
<tr><td class="text">Buy call</td><td class="text">Price will rise a lot</td><td class="text">Unlimited</td><td class="text">Premium paid</td></tr>
<tr><td class="text">Sell call</td><td class="text">Price will not rise</td><td class="text">Premium received</td><td class="text">Unlimited</td></tr>
<tr><td class="text">Buy put</td><td class="text">Price will fall a lot</td><td class="text">Strike − premium</td><td class="text">Premium paid</td></tr>
<tr><td class="text">Sell put</td><td class="text">Price will not fall</td><td class="text">Premium received</td><td class="text">Strike − premium (huge)</td></tr>
</tbody></table></div>`,
      quiz: [
        { q: 'When does a put buyer make money?', opts: ['When the market rises', 'When the market falls below strike − premium', 'When nothing happens', 'Always'], a: 1, why: 'A put gains as price falls. It is profitable at expiry once price is below strike minus premium.' },
        { q: 'You sell a 24,900 put for ₹110. NIFTY expires at 25,200. Your P&L per unit?', opts: ['+₹110', '−₹300', '+₹300', '−₹110'], a: 0, why: 'The put expires worthless because 25,200 is above 24,900, so the seller keeps the full ₹110 premium.' },
        { q: 'Why are puts compared to insurance?', opts: ['They are sold by insurance companies', 'You pay a premium to be protected against a fall', 'They never expire', 'They are free'], a: 1, why: 'Like an insurance premium, you pay a small known amount to be protected from a large loss if prices drop.' },
      ],
    },
    {
      id: 'terms', title: 'Moneyness, expiry and settlement',
      html: `
<div class="eyebrow">Lesson 4</div>
<h1>Moneyness, expiry and settlement</h1>
<h2>In, at or out of the money</h2>
<p>Traders describe where the strike sits relative to today's price:</p>
<ul>
  <li><b>At the money (ATM)</b>: strike ≈ current price. NIFTY 25,000, strike 25,000.</li>
  <li><b>In the money (ITM)</b>: the option would be worth something if it expired right now. Calls with strike <i>below</i> spot, puts with strike <i>above</i> spot.</li>
  <li><b>Out of the money (OTM)</b>: it would be worthless right now. Calls with strike above spot, puts with strike below spot.</li>
</ul>
<p>OTM options are cheap because they need a big move to pay off. Most OTM options expire worthless, which is why buying only cheap far-OTM options is a common way to slowly lose money.</p>
<h2>Intrinsic value and time value</h2>
<p>An option's premium has two parts:</p>
<ul>
  <li><b>Intrinsic value</b>: what it is worth if exercised now. A 24,800 call with NIFTY at 25,000 has 200 of intrinsic value.</li>
  <li><b>Time value</b>: everything above intrinsic value. It is the price of <i>possibility</i>, the chance the option becomes more valuable before expiry. OTM options are 100% time value.</li>
</ul>
<p>Time value shrinks every day and is exactly zero at expiry. This decay is called <b>theta</b> (lesson 7).</p>
<h2>Expiry and settlement in India</h2>
<ul>
  <li>Index options on NSE are <b>European style</b>: they can only be exercised at expiry, but you can sell them any time before.</li>
  <li>They are <b>cash settled</b>: no shares change hands. At expiry, ITM options pay the difference between the settlement price and the strike, in cash.</li>
  <li>NIFTY has <b>weekly</b> expiries; most other index contracts are monthly. SEBI's late-2024 rules limit each exchange to one weekly index expiry. Expiry weekdays have changed over the years, so check the current exchange calendar.</li>
  <li>Most traders never hold to expiry. They <b>square off</b> (close) the position earlier by doing the opposite trade.</li>
</ul>`,
      quiz: [
        { q: 'NIFTY is at 25,000. Which option is in the money?', opts: ['25,200 call', '24,800 put', '24,800 call', '25,000 call'], a: 2, why: 'A call is ITM when strike < spot: the 24,800 call has 200 of intrinsic value.' },
        { q: 'A 25,200 call trades at ₹60 with NIFTY at 25,000. How much is time value?', opts: ['₹0', '₹60', '₹200', '₹260'], a: 1, why: 'It is OTM (strike above spot) so intrinsic value is 0 and the whole ₹60 is time value.' },
        { q: 'What happens to time value at expiry?', opts: ['It doubles', 'It becomes zero', 'It stays the same', 'It turns into intrinsic value'], a: 1, why: 'At expiry there is no time left for anything to change, so an option is worth only its intrinsic value.' },
      ],
    },
    {
      id: 'pricing', title: 'What sets an option\'s price',
      html: `
<div class="eyebrow">Lesson 5</div>
<h1>What sets an option's price</h1>
<p>Five inputs decide a fair option price. The standard formula that combines them is <b>Black–Scholes</b>, and trading platforms including Sensibull use models like it.</p>
<ol>
  <li><b>Spot price</b> of the underlying.</li>
  <li><b>Strike price</b>.</li>
  <li><b>Time to expiry</b>: more time means more chance of a big move, so a higher price.</li>
  <li><b>Volatility</b>: how much the market expects the price to swing. More expected movement means more expensive options, both calls and puts.</li>
  <li><b>Interest rate</b>: a minor effect for short-dated options.</li>
</ol>
<p>Play with the sliders. Watch how the call and put react differently to spot, but the same way to time and volatility.</p>
<div class="widget" data-widget="pricer"></div>
<div class="callout"><p><b>Key insight.</b> Volatility is the only input you cannot see directly. When you trade options you are really trading a view on <i>how much</i> the price will move, not just <i>which way</i>. Lesson 8 covers this in depth.</p></div>`,
      quiz: [
        { q: 'Volatility rises while everything else is unchanged. What happens?', opts: ['Calls rise, puts fall', 'Both calls and puts become more expensive', 'Both get cheaper', 'Nothing'], a: 1, why: 'Higher expected movement increases the chance of a big payoff for both calls and puts.' },
        { q: 'Which option is worth more, all else equal?', opts: ['One expiring in 7 days', 'One expiring in 30 days', 'They are equal', 'It depends on the lot size'], a: 1, why: 'More time means more chance of a favourable move, so the longer-dated option costs more.' },
        { q: 'Which pricing input cannot be observed directly?', opts: ['Spot price', 'Strike price', 'Volatility', 'Time to expiry'], a: 2, why: 'Future volatility is unknown. The market\'s estimate of it, implied volatility, is backed out from option prices.' },
      ],
    },
    {
      id: 'delta', title: 'Delta and gamma',
      html: `
<div class="eyebrow">Lesson 6</div>
<h1>The Greeks, part 1: delta and gamma</h1>
<p>The "Greeks" measure how an option's price responds to changes in its inputs. They are your risk dashboard.</p>
<h2>Delta: sensitivity to price</h2>
<p><b>Delta</b> tells you how much the option moves when the underlying moves by 1 point.</p>
<ul>
  <li>Calls have delta between 0 and +1. Puts have delta between −1 and 0.</li>
  <li>An ATM option has delta around ±0.5. A deep ITM option is near ±1 and behaves like the underlying. A far OTM option is near 0.</li>
  <li>Example: a call with delta 0.4 gains about ₹0.40 when NIFTY rises 1 point. With ${LOT} units per lot, a 100-point NIFTY rally adds about 0.4 × 100 × ${LOT} = ₹${(0.4 * 100 * LOT).toLocaleString('en-IN')}.</li>
  <li>Traders also read delta as a rough probability that the option ends in the money. A 0.16-delta put has roughly a 16% chance of finishing ITM.</li>
</ul>
<h2>Gamma: how fast delta changes</h2>
<p><b>Gamma</b> is how much delta changes per 1-point move. It is highest for ATM options close to expiry. High gamma means your position's risk can change very quickly, which is great for buyers when the market moves and dangerous for sellers.</p>
<p>Use the pricer below: move the spot slider and watch delta. Then set days to 1 and see how sharply delta jumps around the strike. That is high gamma.</p>
<div class="widget" data-widget="pricer"></div>
<div class="callout warn"><p><b>Expiry-day gamma.</b> An ATM option on expiry day can swing from almost worthless to hugely valuable within minutes. Sellers of these options can see losses multiply very fast.</p></div>`,
      quiz: [
        { q: 'A put has delta −0.30. NIFTY rises 100 points. Roughly what happens to the put price?', opts: ['Rises ₹30', 'Falls ₹30', 'Rises ₹100', 'Unchanged'], a: 1, why: 'Price change ≈ delta × move = −0.30 × 100 = −₹30.' },
        { q: 'Where is gamma highest?', opts: ['Deep ITM, far expiry', 'Far OTM, far expiry', 'ATM, close to expiry', 'It is constant'], a: 2, why: 'Near expiry an ATM option\'s delta flips between 0 and 1 over a small price range: that is maximum gamma.' },
        { q: 'A 0.10-delta call roughly means…', opts: ['It costs ₹0.10', 'About a 10% chance of finishing in the money', '10 days to expiry', '10% of the lot'], a: 1, why: 'Delta is commonly used as a rough probability of expiring ITM.' },
      ],
    },
    {
      id: 'theta', title: 'Theta and vega',
      html: `
<div class="eyebrow">Lesson 7</div>
<h1>The Greeks, part 2: theta and vega</h1>
<h2>Theta: the cost of time</h2>
<p><b>Theta</b> is how much value an option loses per day, all else equal. It is negative for buyers (you pay for time) and positive for sellers (you earn it).</p>
<p>Decay is <b>not linear</b>. An ATM option loses value slowly at first and then faster and faster in its final days. The chart shows an ATM NIFTY call's value as expiry approaches with nothing else changing.</p>
<div class="widget" data-widget="decay"></div>
<h2>Vega: sensitivity to volatility</h2>
<p><b>Vega</b> is how much the option price changes for a 1 percentage point change in implied volatility. If a call has vega 12 and IV rises from 13% to 15%, the call gains about ₹24 even if NIFTY doesn't move.</p>
<ul>
  <li>Buyers are <b>long vega</b>: they benefit when volatility rises (for example before big events).</li>
  <li>Sellers are <b>short vega</b>: they benefit when volatility falls (for example the day after an event, the "IV crush").</li>
  <li>Longer-dated options have more vega.</li>
</ul>
<div class="callout"><p><b>The core trade-off.</b> Option buyers fight theta every day and need a big, fast move. Option sellers earn theta every day but are exposed to sudden large moves via gamma and vega. There is no free lunch on either side.</p></div>`,
      quiz: [
        { q: 'When does an ATM option lose time value fastest?', opts: ['Months before expiry', 'In the last few days before expiry', 'Evenly throughout', 'Only on weekends'], a: 1, why: 'Time decay accelerates as expiry approaches, especially for ATM options.' },
        { q: 'You bought a straddle and IV collapses after an event, with no price move. What happens?', opts: ['You profit', 'You lose (short on time, long vega)', 'Nothing', 'You get your premium back'], a: 1, why: 'Buyers are long vega. Falling IV lowers option prices even if spot is unchanged.' },
        { q: 'A call has vega 10. IV rises 3 points. Roughly how does its price change?', opts: ['+₹3', '+₹10', '+₹30', '−₹30'], a: 2, why: 'Vega × change in IV = 10 × 3 = +₹30.' },
      ],
    },
    {
      id: 'iv', title: 'Implied volatility and India VIX',
      html: `
<div class="eyebrow">Lesson 8</div>
<h1>Implied volatility and India VIX</h1>
<p><b>Implied volatility (IV)</b> is the volatility number that, plugged into the pricing formula, reproduces the option's market price. It is the market's forecast of how much the price will swing, expressed as an annualised percentage.</p>
<h2>Reading IV</h2>
<p>A rule of thumb converts IV into an expected move: <b>expected move ≈ spot × IV × √(days / 365)</b>. With NIFTY at 25,000 and IV of 13%, the one-week expected move is about 25,000 × 0.13 × √(7/365) ≈ <b>450 points</b>. Roughly two weeks in three, NIFTY should stay within ±450 points.</p>
<h2>India VIX</h2>
<p><b>India VIX</b> is an index of NIFTY's near-term implied volatility, published by NSE. It is often called the "fear gauge". It tends to jump when markets fall sharply and drift lower during calm rallies.</p>
<h2>IV rank and IV percentile</h2>
<p>Is 15% IV high or low? It depends on history. <b>IV rank</b> places today's IV within its range over the past year: 0 means the lowest level of the year, 100 means the highest. Sellers prefer high IV rank because premiums are rich. Buyers prefer low IV rank because options are cheap.</p>
<h2>Skew</h2>
<p>IV differs by strike. On Indian indices, OTM puts usually trade at higher IV than OTM calls because investors pay up for crash protection. Plotting IV against strike gives the <b>volatility smile</b> or <b>skew</b>. The Live page shows it for the real chain.</p>
<h2>Realised vs implied</h2>
<p><b>Realised volatility</b> is how much the price actually moved. Historically, implied volatility has on average been a little higher than the volatility that followed. That gap, the <b>volatility risk premium</b>, is why option sellers can profit over time. It is also why they occasionally suffer huge losses when a crash makes realised volatility explode.</p>`,
      quiz: [
        { q: 'NIFTY is at 24,000 and IV is 16%. What is the approximate one-month (30 day) expected move?', opts: ['About 1,100 points', 'About 3,840 points', 'About 160 points', 'About 16 points'], a: 0, why: '24,000 × 0.16 × √(30/365) ≈ 24,000 × 0.16 × 0.287 ≈ 1,100 points.' },
        { q: 'IV rank is 90. What does that mean?', opts: ['IV is 90%', 'IV is near the top of its one-year range', 'Options are cheap', '90% chance of profit'], a: 1, why: 'IV rank compares today\'s IV to its 52-week range. 90 means near the high end.' },
        { q: 'Why do OTM index puts usually carry higher IV than OTM calls?', opts: ['Exchange rules', 'Demand for crash protection', 'They have more time', 'Calls are illegal'], a: 1, why: 'Hedgers buy puts for protection, which bids up their prices and so their implied volatility.' },
      ],
    },
    {
      id: 'strategies', title: 'Core strategies',
      html: `
<div class="eyebrow">Lesson 9</div>
<h1>Core strategies</h1>
<p>Combining options creates payoffs for almost any view: up, down, sideways, or "big move either way". Pick a strategy to see its payoff at expiry (solid line, shaded) and today (dashed line), with NIFTY at 25,000.</p>
<div class="widget" data-widget="strategies"></div>
<h2>How to choose</h2>
<div class="table-wrap"><table class="data">
<thead><tr><th class="text">Your view</th><th class="text">Consider</th><th class="text">Risk</th></tr></thead>
<tbody>
<tr><td class="text">Moderately bullish</td><td class="text">Bull call spread, bull put spread</td><td class="text">Defined</td></tr>
<tr><td class="text">Moderately bearish</td><td class="text">Bear put spread, bear call spread</td><td class="text">Defined</td></tr>
<tr><td class="text">Range-bound, IV high</td><td class="text">Iron condor, iron butterfly</td><td class="text">Defined</td></tr>
<tr><td class="text">Big move expected, IV low</td><td class="text">Long straddle, long strangle</td><td class="text">Defined (premium)</td></tr>
<tr><td class="text">Range-bound (experienced only)</td><td class="text">Short straddle, short strangle</td><td class="text">Undefined, large</td></tr>
<tr><td class="text">Own the stock, want protection</td><td class="text">Protective put</td><td class="text">Defined</td></tr>
</tbody></table></div>
<div class="callout good"><p><b>Beginner rule.</b> Start with <b>defined-risk</b> strategies (spreads, condors) where the maximum loss is known before you enter. They also need far less margin than naked short options.</p></div>`,
      quiz: [
        { q: 'You expect NIFTY to stay in a range and IV is high. Which fits best?', opts: ['Long straddle', 'Iron condor', 'Buy a call', 'Buy a put'], a: 1, why: 'An iron condor profits if price stays between the short strikes and benefits as high IV falls, with capped risk.' },
        { q: 'What is the main advantage of a bull call spread over buying a call?', opts: ['Unlimited profit', 'Lower cost and lower breakeven', 'No expiry', 'No risk at all'], a: 1, why: 'Selling the higher call reduces the net premium. That lowers cost and breakeven, in exchange for capping profit.' },
        { q: 'Which strategy has undefined (unlimited) risk?', opts: ['Iron condor', 'Bear put spread', 'Short strangle', 'Long straddle'], a: 2, why: 'A short strangle sells naked options on both sides, so a big move either way causes uncapped losses.' },
      ],
    },
    {
      id: 'risk', title: 'Risk, margin and position sizing',
      html: `
<div class="eyebrow">Lesson 10</div>
<h1>Risk, margin and position sizing</h1>
<div class="callout bad"><p><b>The uncomfortable statistic.</b> SEBI's 2024 study of individual F&amp;O traders found that about <b>93% lost money</b> over FY22 to FY24, with aggregate losses above ₹1.8 lakh crore. Most losses come from oversized positions, naked option selling without protection, and repeatedly buying cheap OTM options.</p></div>
<h2>Margin</h2>
<p>Buying an option only requires paying the premium. <b>Selling</b> an option requires <b>margin</b>, a deposit the broker blocks to cover potential losses. For a naked index option this can be over a lakh of rupees per lot. Hedged positions such as spreads need far less margin because the maximum loss is capped. If losses eat into your margin, your broker can close your position at the worst possible moment.</p>
<h2>Position sizing</h2>
<p>The most important decision is not <i>what</i> to trade but <i>how much</i>. A common rule: never risk more than <b>1–2% of your capital</b> on a single trade. Risk means the amount you lose if the trade hits your stop or its maximum loss.</p>
<div class="widget" data-widget="sizing"></div>
<h2>Rules that keep you in the game</h2>
<ul>
  <li><b>Know your maximum loss before entering.</b> If you can't state it, don't trade it.</li>
  <li><b>Use stop losses</b> or defined-risk structures. Decide the exit before the entry.</li>
  <li><b>Avoid naked short options</b> until you have real experience and a large account.</li>
  <li><b>Beware expiry-day trading</b>: very high gamma makes it close to gambling.</li>
  <li><b>Costs add up</b>: brokerage, STT, exchange charges, GST and slippage are paid on every leg of every trade.</li>
  <li><b>Keep a journal</b>: record why you entered, what happened and what you learned.</li>
</ul>`,
      quiz: [
        { q: 'You have ₹5,00,000 and follow a 2% risk rule. What is the most you should risk per trade?', opts: ['₹1,000', '₹10,000', '₹50,000', '₹1,00,000'], a: 1, why: '2% of ₹5,00,000 = ₹10,000.' },
        { q: 'Why does selling an option need margin but buying does not?', opts: ['Sellers can lose far more than the premium', 'Exchanges prefer buyers', 'Buyers pay more tax', 'It does not'], a: 0, why: 'A buyer\'s loss is capped at the premium already paid. A seller\'s loss can be many times the premium, so collateral is required.' },
        { q: 'According to SEBI\'s 2024 study, roughly what share of individual F&O traders lost money over FY22 to FY24?', opts: ['About 10%', 'About 50%', 'About 93%', 'About 30%'], a: 2, why: 'SEBI found around 93% of individual traders incurred net losses over that period.' },
      ],
    },
    {
      id: 'chain', title: 'Reading an option chain',
      html: `
<div class="eyebrow">Lesson 11</div>
<h1>Reading an option chain</h1>
<p>An <b>option chain</b> lists every strike for one expiry, with calls on the left and puts on the right. The Live page shows one. Here is what each column means:</p>
<dl class="gloss">
  <dt>Strike</dt><dd>The middle column. The ATM strike (closest to spot) is highlighted. ITM cells are shaded.</dd>
  <dt>LTP (last traded price)</dt><dd>The latest premium per unit.</dd>
  <dt>IV</dt><dd>Implied volatility for that strike and type.</dd>
  <dt>Delta</dt><dd>Price sensitivity and a rough probability of ending ITM.</dd>
  <dt>OI (open interest)</dt><dd>The number of contracts currently open. High OI at a strike shows where traders have placed large bets; big call OI above spot is often read as "resistance", big put OI below spot as "support".</dd>
  <dt>Volume</dt><dd>Contracts traded today. High volume means good liquidity and tighter bid–ask spreads.</dd>
</dl>
<h2>Derived numbers</h2>
<ul>
  <li><b>PCR (put–call ratio)</b> = total put OI ÷ total call OI. Above 1 means more puts are open than calls. Traders argue over whether that is bullish or bearish, so treat it as context rather than a signal.</li>
  <li><b>Max pain</b>: the strike at which option buyers as a group would lose the most at expiry. Some believe prices gravitate toward it near expiry. The evidence is mixed.</li>
  <li><b>ATM IV</b>: the headline implied volatility for the expiry.</li>
</ul>
<h2>Liquidity matters</h2>
<p>Stick to strikes near the money with high OI and volume. Illiquid far strikes can have wide bid–ask spreads, so you lose money the moment you trade.</p>
<p>On the <a href="live.html">Live page</a> you can click <b>B</b> or <b>S</b> next to any price to add that leg to the strategy builder and see its payoff.</p>`,
      quiz: [
        { q: 'Total put OI is 1.2 crore and total call OI is 1.0 crore. What is the PCR?', opts: ['0.83', '1.2', '2.2', '0.2'], a: 1, why: 'PCR = put OI ÷ call OI = 1.2 ÷ 1.0 = 1.2.' },
        { q: 'Why prefer strikes with high volume and OI?', opts: ['They always profit', 'Better liquidity and tighter spreads', 'Lower taxes', 'No margin needed'], a: 1, why: 'Liquid strikes let you enter and exit close to fair value.' },
        { q: 'Where does a chain show the ATM strike?', opts: ['The first row', 'The strike nearest the current spot price', 'The highest OI', 'The last row'], a: 1, why: 'ATM is the strike closest to the underlying\'s current price.' },
      ],
    },
    {
      id: 'practice', title: 'From paper trading to real trading',
      html: `
<div class="eyebrow">Lesson 12</div>
<h1>From paper trading to real trading</h1>
<p>You now know more than most people who place their first options trade. Here is a safe path forward.</p>
<ol>
  <li><b>Paper trade for at least a month.</b> Use the <a href="live.html">Live page</a> strategy builder to place imaginary trades on the real chain and track their P&amp;L. Write down every trade and the reason for it.</li>
  <li><b>Pick one or two defined-risk strategies</b> and learn them deeply: when they work, when they fail, how to adjust or exit.</li>
  <li><b>Backtest ideas</b> before risking money. The <a href="agent.html">Research agent</a> page runs hundreds of strategy variants against historical or simulated data and shows which rules held up on data they were not tuned on.</li>
  <li><b>Start tiny.</b> One lot of a spread, with money you can afford to lose entirely.</li>
  <li><b>Review monthly.</b> Compare results with your paper-trading expectations. Scale up only after a long stretch of consistent, disciplined execution.</li>
</ol>
<h2>A warning about backtests</h2>
<p>A strategy that looks brilliant on past data can fail in live markets. Common reasons:</p>
<ul>
  <li><b>Overfitting</b>: tuning many parameters until the past looks perfect. The more you search, the more you fool yourself. Always keep test data the optimiser never sees.</li>
  <li><b>Unrealistic fills</b>: real trades pay spreads, slippage and charges.</li>
  <li><b>Regime change</b>: markets behave differently in crashes, rallies and quiet periods.</li>
  <li><b>Tail events</b>: a strategy that wins 95% of the time can lose years of gains in one day.</li>
</ul>
<h2>Glossary</h2>
<dl class="gloss">
  <dt>ATM / ITM / OTM</dt><dd>At, in or out of the money: where the strike sits relative to spot.</dd>
  <dt>Breakeven</dt><dd>Underlying price at expiry where the trade neither makes nor loses money.</dd>
  <dt>Credit / debit</dt><dd>Net premium received (credit) or paid (debit) when opening a position.</dd>
  <dt>Exercise</dt><dd>Using the option's right. Indian index options are cash-settled at expiry.</dd>
  <dt>Hedge</dt><dd>A position taken to offset the risk of another.</dd>
  <dt>Lot</dt><dd>The fixed contract size set by the exchange.</dd>
  <dt>Premium</dt><dd>The price of an option.</dd>
  <dt>Square off</dt><dd>Close a position by taking the opposite trade.</dd>
  <dt>Strike</dt><dd>The fixed price at which the option can be exercised.</dd>
  <dt>Writer</dt><dd>The seller of an option.</dd>
</dl>`,
      quiz: [
        { q: 'A strategy made 80% a year in a backtest after you tested 500 variations. What is the main risk?', opts: ['Taxes', 'Overfitting: it may be tuned to noise', 'None, 80% is proven', 'Too little margin'], a: 1, why: 'Searching many variants on the same data almost guarantees some look great by luck. Validate on unseen data.' },
        { q: 'What is a sensible first real trade after paper trading?', opts: ['Ten lots of naked short straddles', 'One lot of a defined-risk spread', 'All capital in far OTM calls', 'Expiry-day scalping'], a: 1, why: 'Start small with a known maximum loss while you learn how real execution feels.' },
      ],
    },
  ];

  // ---------------------------------------------------------------- state
  const state = { idx: 0, done: new Set(store.get('learn.done', [])), answers: store.get('learn.answers', {}) };
  const saveProgress = () => { store.set('learn.done', [...state.done]); store.set('learn.answers', state.answers); };

  const listEl = document.getElementById('lesson-list');
  const lessonEl = document.getElementById('lesson');

  function renderNav() {
    listEl.innerHTML = LESSONS.map((l, i) => `
      <li class="${state.done.has(l.id) ? 'done' : ''}">
        <button data-i="${i}" ${i === state.idx ? 'aria-current="true"' : ''}>
          <span class="n">${state.done.has(l.id) ? '✓' : i + 1}</span><span>${esc(l.title)}</span>
        </button>
      </li>`).join('');
    const n = LESSONS.filter((l) => state.done.has(l.id)).length;
    document.getElementById('progress-text').textContent = `${n} of ${LESSONS.length} lessons complete`;
    document.getElementById('progress-bar').style.width = (100 * n / LESSONS.length) + '%';
  }
  listEl.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-i]');
    if (b) go(+b.dataset.i);
  });

  function go(i) {
    state.idx = Math.max(0, Math.min(LESSONS.length - 1, i));
    store.set('learn.idx', state.idx);
    history.replaceState(null, '', '#' + LESSONS[state.idx].id);
    render();
    window.scrollTo({ top: 0 });
  }

  function render() {
    const L = LESSONS[state.idx];
    const quizHtml = (L.quiz || []).map((q, qi) => {
      const key = `${L.id}.${qi}`;
      return `<div class="quiz" data-key="${key}">
        <div class="q">Check: ${esc(q.q)}</div>
        <div class="opts">${q.opts.map((o, oi) => `<button data-oi="${oi}">${esc(o)}</button>`).join('')}</div>
        <div class="explain" hidden></div></div>`;
    }).join('');
    lessonEl.innerHTML = L.html + (quizHtml ? `<h2>Quick check</h2>${quizHtml}` : '') + `
      <div class="lesson-foot">
        <button class="btn ghost" id="prev" ${state.idx === 0 ? 'disabled' : ''}>← Previous</button>
        <button class="btn" id="next">${state.idx === LESSONS.length - 1 ? 'Finish ✓' : 'Mark complete & next →'}</button>
      </div>`;
    // restore quiz answers
    lessonEl.querySelectorAll('.quiz').forEach((qEl) => {
      const prev = state.answers[qEl.dataset.key];
      if (prev !== undefined) answer(qEl, prev, false);
    });
    lessonEl.querySelectorAll('.widget').forEach(mountWidget);
    document.getElementById('prev').onclick = () => go(state.idx - 1);
    document.getElementById('next').onclick = () => {
      state.done.add(L.id); saveProgress();
      if (state.idx < LESSONS.length - 1) go(state.idx + 1);
      else { renderNav(); OD.toast('Course complete. Head to the Live page to paper-trade.'); }
    };
    renderNav();
  }

  function answer(qEl, oi, save = true) {
    const [lid, qi] = qEl.dataset.key.split('.');
    const q = LESSONS.find((l) => l.id === lid).quiz[+qi];
    qEl.querySelectorAll('button').forEach((b, i) => {
      b.disabled = true;
      if (i === q.a) b.classList.add('right');
      else if (i === oi) b.classList.add('wrong');
    });
    const ex = qEl.querySelector('.explain');
    ex.hidden = false;
    ex.innerHTML = (oi === q.a ? '<b class="pos">Correct.</b> ' : '<b class="neg">Not quite.</b> ') + esc(q.why);
    if (save) { state.answers[qEl.dataset.key] = oi; saveProgress(); }
  }
  lessonEl.addEventListener('click', (e) => {
    const b = e.target.closest('.quiz .opts button');
    if (b && !b.disabled) answer(b.closest('.quiz'), +b.dataset.oi);
  });

  // ---------------------------------------------------------------- widgets
  function slider(id, label, min, max, step, value, fmtFn) {
    return `<div class="slider-row"><label for="${id}">${label}</label>
      <input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${value}">
      <output for="${id}" data-fmt="${fmtFn || ''}"></output></div>`;
  }
  function bindSliders(root, onChange) {
    const inputs = root.querySelectorAll('input[type=range], select, [data-seg] button');
    const update = () => {
      root.querySelectorAll('.slider-row').forEach((r) => {
        const inp = r.querySelector('input'); const out = r.querySelector('output');
        const v = +inp.value; const f = out.dataset.fmt;
        out.textContent = f === 'pct' ? v + '%' : f === 'days' ? v + (v === 1 ? ' day' : ' days') : f === 'rs' ? '₹' + fmt.n(v, 0) : fmt.n(v, 0);
      });
      onChange();
    };
    inputs.forEach((i) => i.addEventListener(i.tagName === 'BUTTON' ? 'click' : 'input', () => {
      if (i.tagName === 'BUTTON') { i.parentElement.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', b === i)); }
      update();
    }));
    update();
  }
  const segVal = (root, name) => root.querySelector(`[data-seg="${name}"] button[aria-pressed="true"]`).dataset.v;

  function mountWidget(el) {
    const kind = el.dataset.widget;
    if (kind === 'payoff') return widgetPayoff(el);
    if (kind === 'pricer') return widgetPricer(el);
    if (kind === 'decay') return widgetDecay(el);
    if (kind === 'strategies') return widgetStrategies(el);
    if (kind === 'sizing') return widgetSizing(el);
  }

  function widgetPayoff(el) {
    const type = el.dataset.type;
    const defK = type === 'C' ? 25000 : 24900, defP = type === 'C' ? 150 : 110;
    el.innerHTML = `<h4>Try it: ${type === 'C' ? 'call' : 'put'} payoff at expiry</h4>
      <div class="row" style="margin-bottom:10px"><div class="seg" data-seg="side"><button data-v="1" aria-pressed="true">Buy</button><button data-v="-1" aria-pressed="false">Sell</button></div>
      <span class="small muted">1 lot = ${LOT} units</span></div>
      ${slider('k', 'Strike', 24000, 26000, 50, defK)}
      ${slider('p', 'Premium', 10, 500, 5, defP, 'rs')}
      ${slider('x', 'NIFTY at expiry', 23500, 26500, 10, type === 'C' ? 25400 : 24300)}
      <div class="chart-box short"><canvas></canvas></div>
      <div class="readout"></div>`;
    const cv = el.querySelector('canvas'); const out = el.querySelector('.readout');
    bindSliders(el, () => {
      const side = +segVal(el, 'side'); const K = +el.querySelector('#k').value; const P = +el.querySelector('#p').value; const X = +el.querySelector('#x').value;
      const legs = [{ type, side, K, lots: 1, premium: P }];
      const st = payoffStats(legs, LOT, 23500, 26500, 300);
      payoffChart(cv, [{ label: 'P&L at expiry', data: st.xs.map((x, i) => ({ x, y: st.ys[i] })), color: css('--accent'), fill: true }], { spot: X, xLabel: 'NIFTY at expiry' });
      if (cv._chart) { cv._chart.options.plugins.spotLine.label = 'Your scenario'; cv._chart.update(); }
      const intrinsic = type === 'C' ? Math.max(X - K, 0) : Math.max(K - X, 0);
      const pnl = positionPnl(legs, X, LOT);
      const verb = side > 0 ? `You pay ${fmt.rs(P * LOT)} (₹${P} × ${LOT}).` : `You receive ${fmt.rs(P * LOT)} (₹${P} × ${LOT}).`;
      const be = type === 'C' ? K + P : K - P;
      out.innerHTML = `${verb} At expiry with NIFTY at <b>${fmt.n(X, 0)}</b> the ${type === 'C' ? 'call' : 'put'} is worth <b>₹${fmt.n(intrinsic, 0)}</b> per unit.
        Net result: <b class="${fmt.cls(pnl)}">${fmt.rs(pnl)}</b>. Breakeven: <b>${fmt.n(be, 0)}</b>.
        Max ${side > 0 ? 'loss' : 'profit'}: <b>${fmt.rs(P * LOT)}</b>. Max ${side > 0 ? 'profit' : 'loss'}: <b>${type === 'C' ? 'unlimited' : fmt.rs((K - P) * LOT)}</b>.`;
    });
  }

  function widgetPricer(el) {
    el.innerHTML = `<h4>Try it: Black–Scholes option pricer</h4>
      ${slider('s', 'NIFTY spot', 23500, 26500, 10, 25000)}
      ${slider('k', 'Strike', 23500, 26500, 50, 25000)}
      ${slider('d', 'Days to expiry', 0, 90, 1, 14, 'days')}
      ${slider('v', 'Implied volatility', 5, 60, 1, 13, 'pct')}
      <div class="grid two" style="margin-top:10px">
        <div><div class="side-head ce small" style="font-weight:700">CALL</div><dl class="kv" id="call"></dl></div>
        <div><div class="side-head pe small" style="font-weight:700">PUT</div><dl class="kv" id="put"></dl></div>
      </div>`;
    bindSliders(el, () => {
      const S = +el.querySelector('#s').value, K = +el.querySelector('#k').value, d = +el.querySelector('#d').value, v = +el.querySelector('#v').value / 100;
      const T = d / 365;
      for (const [type, id] of [['C', 'call'], ['P', 'put']]) {
        const r = bs(type, S, K, T, v);
        const intr = type === 'C' ? Math.max(S - K, 0) : Math.max(K - S, 0);
        const m = Math.abs(S - K) < 25 ? 'ATM' : ((type === 'C' ? S > K : S < K) ? 'ITM' : 'OTM');
        el.querySelector('#' + id).innerHTML = `
          <dt>Price</dt><dd><b>₹${fmt.px(r.price)}</b> (${m})</dd>
          <dt>Intrinsic / time</dt><dd>${fmt.px(intr)} / ${fmt.px(Math.max(r.price - intr, 0))}</dd>
          <dt>Per lot</dt><dd>${fmt.rs(r.price * LOT)}</dd>
          <dt>Delta</dt><dd>${r.delta.toFixed(3)}</dd>
          <dt>Gamma</dt><dd>${r.gamma.toFixed(5)}</dd>
          <dt>Theta / day</dt><dd>${fmt.px(r.theta)}</dd>
          <dt>Vega / 1% IV</dt><dd>${fmt.px(r.vega)}</dd>`;
      }
    });
  }

  function widgetDecay(el) {
    el.innerHTML = `<h4>ATM call value vs days to expiry (NIFTY 25,000)</h4>
      ${slider('v', 'Implied volatility', 5, 40, 1, 13, 'pct')}
      <div class="chart-box short"><canvas></canvas></div>
      <div class="readout"></div>`;
    const cv = el.querySelector('canvas');
    bindSliders(el, () => {
      const v = +el.querySelector('#v').value / 100;
      const data = []; for (let d = 60; d >= 0; d--) data.push({ x: d, y: bs('C', 25000, 25000, d / 365, v).price });
      payoffChart(cv, [{ label: 'Call value', data, color: css('--call') }], { xLabel: 'Days to expiry', yLabel: 'Option price (₹ per unit)' });
      if (cv._chart) {
        cv._chart.options.scales.x.reverse = true;
        cv._chart.options.scales.y.ticks.callback = (x) => '₹' + x.toFixed(0);
        cv._chart.options.plugins.tooltip.callbacks = { title: (it) => it[0].parsed.x + ' days left', label: (it) => ` Value: ₹${it.parsed.y.toFixed(2)}` };
        cv._chart.update();
      }
      const p30 = bs('C', 25000, 25000, 30 / 365, v).price, p23 = bs('C', 25000, 25000, 23 / 365, v).price;
      const p7 = bs('C', 25000, 25000, 7 / 365, v).price;
      el.querySelector('.readout').innerHTML = `From 30 to 23 days left the option loses <b>₹${(p30 - p23).toFixed(0)}</b>. In the final 7 days it loses <b>₹${p7.toFixed(0)}</b>, all of its remaining value.`;
    });
  }

  // Strategy templates relative to spot S (strikes rounded to 50)
  const STRATS = {
    long_call: { name: 'Long call', view: 'Strongly bullish', legs: (S) => [['C', 1, S]], note: 'Pay a premium for unlimited upside. Loses if NIFTY does not rise past the breakeven before expiry.' },
    long_put: { name: 'Long put', view: 'Strongly bearish', legs: (S) => [['P', 1, S]], note: 'Pay a premium to profit from a fall. Useful as portfolio insurance.' },
    bull_call: { name: 'Bull call spread', view: 'Moderately bullish', legs: (S) => [['C', 1, S], ['C', -1, S + 300]], note: 'Buy an ATM call, sell a higher call. Cheaper than a naked call, with profit capped at the upper strike.' },
    bear_put: { name: 'Bear put spread', view: 'Moderately bearish', legs: (S) => [['P', 1, S], ['P', -1, S - 300]], note: 'Buy an ATM put, sell a lower put. Defined risk and defined reward.' },
    bull_put: { name: 'Bull put spread (credit)', view: 'Neutral to bullish', legs: (S) => [['P', -1, S - 200], ['P', 1, S - 500]], note: 'Collect premium by selling a put and buying a further OTM put as protection. Profits if NIFTY stays above the short strike.' },
    iron_condor: { name: 'Iron condor', view: 'Range-bound', legs: (S) => [['P', 1, S - 700], ['P', -1, S - 400], ['C', -1, S + 400], ['C', 1, S + 700]], note: 'Sell an OTM put spread and an OTM call spread. Profits if NIFTY stays between the short strikes. Losses capped by the wings.' },
    iron_fly: { name: 'Iron butterfly', view: 'Pinned near spot', legs: (S) => [['P', 1, S - 400], ['P', -1, S], ['C', -1, S], ['C', 1, S + 400]], note: 'Sell an ATM straddle and buy wings. Higher credit than a condor but a narrower profit zone.' },
    long_straddle: { name: 'Long straddle', view: 'Big move, either way', legs: (S) => [['C', 1, S], ['P', 1, S]], note: 'Buy an ATM call and put. Profits from a large move in either direction. Loses to time decay if the market stays still.' },
    long_strangle: { name: 'Long strangle', view: 'Very big move', legs: (S) => [['C', 1, S + 300], ['P', 1, S - 300]], note: 'Cheaper than a straddle but needs a larger move.' },
    short_straddle: { name: 'Short straddle', view: 'Very quiet market', legs: (S) => [['C', -1, S], ['P', -1, S]], note: 'Sell an ATM call and put. Maximum profit if NIFTY expires exactly at the strike. Unlimited risk. Experienced traders only.' },
    short_strangle: { name: 'Short strangle', view: 'Range-bound', legs: (S) => [['C', -1, S + 400], ['P', -1, S - 400]], note: 'Sell OTM call and put. Wide profit zone but unlimited risk on sharp moves.' },
    protective_put: { name: 'Protective put', view: 'Own the index, fear a fall', legs: (S) => [['F', 1, S], ['P', 1, S - 200]], note: 'Hold the underlying (shown as a future) and buy a put. Losses below the put strike are capped, like insurance.' },
  };
  function buildStrategy(key, S, days, iv) {
    const T = days / 365;
    return STRATS[key].legs(S).map(([type, side, K]) => ({
      type, side, K, lots: 1, iv, T,
      premium: type === 'F' ? S : bs(type, S, K, T, iv).price,
    }));
  }

  function widgetStrategies(el) {
    el.innerHTML = `<h4>Strategy explorer</h4>
      <div class="form-grid" style="margin-bottom:10px">
        <label class="field"><span>Strategy</span><select id="st">${Object.entries(STRATS).map(([k, s]) => `<option value="${k}">${s.name}</option>`).join('')}</select></label>
      </div>
      ${slider('d', 'Days to expiry', 1, 60, 1, 21, 'days')}
      ${slider('v', 'Implied volatility', 5, 40, 1, 13, 'pct')}
      <div class="chart-box"><canvas></canvas></div>
      <div class="legend"><span><i style="background:${css('--accent')}"></i>At expiry</span><span><i style="background:${css('--muted')}"></i>Today (dashed)</span></div>
      <div class="readout"></div>`;
    const cv = el.querySelector('canvas');
    bindSliders(el, () => {
      const key = el.querySelector('#st').value, d = +el.querySelector('#d').value, v = +el.querySelector('#v').value / 100;
      const S = 25000; const legs = buildStrategy(key, S, d, v);
      const st = payoffStats(legs, LOT, 23000, 27000, 400);
      const today = st.xs.map((x) => ({ x, y: positionPnl(legs, x, LOT, 0) }));
      payoffChart(cv, [
        { label: 'At expiry', data: st.xs.map((x, i) => ({ x, y: st.ys[i] })), color: css('--accent'), fill: true },
        { label: 'Today', data: today, color: css('--muted'), dashed: true, width: 1.5 },
      ], { spot: S });
      const net = legs.reduce((a, l) => a + (l.type === 'F' ? 0 : -l.side * l.premium), 0) * LOT;
      const s = STRATS[key];
      el.querySelector('.readout').innerHTML = `<p><b>${s.name}</b>: ${s.view}. ${s.note}</p>
        <div class="tiles">
          <div class="tile"><div class="label">Legs</div><div class="value small" style="font-size:.85rem">${legs.map((l) => `${l.side > 0 ? 'Buy' : 'Sell'} ${l.type === 'F' ? 'FUT' : l.K + (l.type === 'C' ? ' CE' : ' PE')}`).join('<br>')}</div></div>
          <div class="tile"><div class="label">${net >= 0 ? 'Net credit' : 'Net debit'}</div><div class="value">${fmt.rs(Math.abs(net))}</div></div>
          <div class="tile"><div class="label">Max profit</div><div class="value pos">${fmt.rs(st.maxProfit)}</div></div>
          <div class="tile"><div class="label">Max loss</div><div class="value neg">${fmt.rs(st.maxLoss)}</div></div>
          <div class="tile"><div class="label">Breakeven</div><div class="value wrap">${st.breakevens.map((b) => fmt.n(b, 0)).join(' / ') || '-'}</div></div>
        </div>`;
    });
  }

  function widgetSizing(el) {
    el.innerHTML = `<h4>Position size calculator</h4>
      ${slider('c', 'Capital', 50000, 5000000, 50000, 500000, 'rs')}
      ${slider('r', 'Risk per trade', 0.5, 5, 0.5, 2, 'pct')}
      ${slider('m', 'Max loss per lot', 1000, 50000, 500, 7500, 'rs')}
      <div class="readout"></div>`;
    bindSliders(el, () => {
      const c = +el.querySelector('#c').value, r = +el.querySelector('#r').value / 100, m = +el.querySelector('#m').value;
      const budget = c * r; const lots = Math.floor(budget / m);
      el.querySelector('.readout').innerHTML = `Risk budget: <b>${fmt.rs(budget)}</b>. Position size: <b>${lots} lot${lots === 1 ? '' : 's'}</b>.
        ${lots === 0 ? '<span class="neg">This trade is too big for your account at this risk level. Choose a narrower spread or skip it.</span>' : `Worst case costs ${fmt.pct(lots * m / c)} of capital. It would take ${Math.ceil(0.5 / (lots * m / c))} such losses in a row to halve your account.`}`;
    });
  }

  // ---------------------------------------------------------------- boot
  const hash = location.hash.slice(1);
  const hi = LESSONS.findIndex((l) => l.id === hash);
  state.idx = hi >= 0 ? hi : Math.min(store.get('learn.idx', 0), LESSONS.length - 1);
  render();
  document.addEventListener('od:theme', () => render());
})();
