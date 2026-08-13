# Judgment Session 3 — q16–q100 (owner-directed, 2026-08-13)

Expands the judgment set from 15 to 100 queries. Labeler: **gpt-5.6-sol**
(owner directive: separate model, larger capacity than session 2's
gpt-5.2). Protocol properties preserved from T-009 / session 2:

- **Criterion-first**: every criterion below was written before any
  pooling or retrieval ran for its query (this file is committed before
  the labeling run starts).
- **Blind pooled grading**: candidates pooled via the frozen
  `pool_candidates` (grep + bm25 + random, shuffled), grader sees ONLY
  criterion + document text. Seed = query number.
- **Resume semantics**: already-judged (query_id, doc_id) pairs skipped.
- **Conservative on failure**: unparseable grades are skipped, never
  fabricated. Rows appended in the exact 5-key schema.
- Provenance sidecar: `evalsets/judgment-session-3-provenance.json`.

q1–q15 are untouched (already pooled + judged against corpus-v2 in
sessions 1–2).

---

### q16: data center rezoning approved acres
A relevant document discusses rezoning land for data-center use; grade 2 for a specific rezoning with acreage, location, applicant, or a vote/decision on record; grade 1 for general rezoning discussion where data centers are at issue but without case-level detail; grade 0 for rezonings unrelated to data centers or data-center talk with no rezoning angle.

### q17: special use permit data center
A relevant document discusses a special/conditional use permit for a data center or supporting infrastructure; grade 2 for a specific permit application, conditions imposed, or an approval/denial decision; grade 1 for general discussion of permit requirements for data centers; grade 0 for use permits unrelated to data centers.

### q18: comprehensive plan amendment technology overlay
A relevant document discusses amending a comprehensive/land-use plan or creating an overlay district to steer data-center or technology development; grade 2 for a specific amendment or overlay with boundaries, policy language, or a vote; grade 1 for general talk of updating the plan for data centers; grade 0 for plan amendments with no data-center/technology connection.

### q19: proffered conditions data center
A relevant document discusses proffers or developer-committed conditions tied to a data-center case; grade 2 for specific proffered commitments (money, infrastructure, limits) with the case identifiable; grade 1 for general discussion of what proffers should be sought; grade 0 for proffers on unrelated projects.

### q20: setback buffer landscaping requirements
A relevant document discusses setbacks, buffers, or screening/landscaping requirements for data centers or large industrial buildings; grade 2 for specific distances/standards adopted, proposed, or applied to a named project; grade 1 for general aesthetics/buffering discussion; grade 0 for setback matters unrelated to industrial/data-center uses.

### q21: building height variance data center
A relevant document discusses building height limits, variances, or exceptions for data-center or industrial structures; grade 2 for a specific height request or standard with numbers or a decision; grade 1 for general height concerns; grade 0 for height matters on unrelated building types.

### q22: data center performance standards ordinance
A relevant document discusses an ordinance or zoning text amendment setting performance standards for data centers (noise limits, design, energy, siting criteria); grade 2 for specific standard text proposed/adopted with a decision or draft language; grade 1 for calls to develop such standards; grade 0 for ordinances unrelated to data centers.

### q23: school funding data center tax revenue
A relevant document discusses school budgets or capital funding in connection with data-center tax revenue; grade 2 for concrete figures or decisions linking data-center revenue to school funding; grade 1 for general claims that data centers fund schools; grade 0 for school funding with no data-center tie.

### q24: property tax revenue projections data center
A relevant document discusses projected or realized property/equipment tax revenue from data centers; grade 2 for dollar figures, rates, or adopted projections tied to data centers; grade 1 for general fiscal-benefit claims; grade 0 for tax discussion with no data-center connection.

### q25: tax abatement incentive package
A relevant document discusses tax abatements, exemptions, or incentive packages for a data center or technology facility; grade 2 for a specific incentive with terms, value, or a vote; grade 1 for general incentive-policy discussion; grade 0 for incentives for unrelated industries.

### q26: PILOT payment in lieu of taxes agreement
A relevant document discusses a payment-in-lieu-of-taxes or similar negotiated payment agreement for an industrial/data-center project; grade 2 for specific agreement terms, amounts, or approval; grade 1 for general PILOT policy discussion; grade 0 for PILOT matters unrelated to industrial/tech projects.

### q27: citizen opposition public hearing data center
A relevant document contains resident testimony, petitions, or organized opposition at a hearing on a data-center matter; grade 2 for substantive opposition on a specific case (named project or docket) with the concerns stated; grade 1 for general anti-data-center sentiment without a case; grade 0 for public comment on unrelated matters.

### q28: traffic study truck trips construction
A relevant document discusses traffic impacts of data-center or industrial construction — trip counts, truck routes, studies, or mitigation; grade 2 for a specific study, count, or imposed condition; grade 1 for general traffic concerns; grade 0 for traffic matters unrelated to industrial development.

### q29: road improvements funded by developer
A relevant document discusses developer-funded road or intersection improvements tied to an industrial/data-center project; grade 2 for specific improvements with cost, scope, or commitment on record; grade 1 for general infrastructure-burden discussion; grade 0 for road projects with no development tie.

### q30: sewer capacity allocation industrial
A relevant document discusses sanitary sewer capacity, allocation, or treatment constraints for industrial or data-center customers; grade 2 for specific capacity numbers, allocation decisions, or upgrade projects; grade 1 for general wastewater-capacity discussion; grade 0 for sewer matters with no industrial-capacity angle.

### q31: groundwater well permit industrial
A relevant document discusses groundwater withdrawal or well permitting for industrial/data-center supply; grade 2 for a specific withdrawal permit, volume, or aquifer decision; grade 1 for general groundwater-impact concerns; grade 0 for well matters unrelated to industrial supply.

### q32: stormwater management pond industrial site
A relevant document discusses stormwater management for an industrial or data-center site — ponds, BMPs, drainage plans, or violations; grade 2 for site-specific facilities, requirements, or enforcement; grade 1 for general stormwater policy touching development; grade 0 for stormwater with no industrial-site connection.

### q33: wetlands permit mitigation industrial development
A relevant document discusses wetlands impacts, permits, or mitigation connected to industrial/data-center development; grade 2 for a specific permit, delineation, or mitigation requirement; grade 1 for general wetlands concerns near development; grade 0 for wetlands matters with no development tie.

### q34: floodplain development industrial
A relevant document discusses floodplain regulation or flood risk affecting industrial/data-center siting; grade 2 for a specific floodplain finding, variance, or siting decision; grade 1 for general flood-risk discussion; grade 0 for floodplain matters unrelated to industrial siting.

### q35: air quality permit emissions facility
A relevant document discusses air-quality permitting or emissions from a data center or industrial facility (excluding the generator-specific angle of q9); grade 2 for a specific permit, emissions limit, or agency action; grade 1 for general air-quality concerns about facilities; grade 0 for air matters with no facility connection.

### q36: substation construction approval
A relevant document discusses siting, approving, or building an electrical substation; grade 2 for a specific substation project with location, capacity, cost, or a decision; grade 1 for general substation-need discussion; grade 0 for electrical matters with no substation angle.

### q37: transmission line routing high voltage
A relevant document discusses high-voltage transmission line projects — routing, easements, approvals, or opposition; grade 2 for a specific line with route, voltage, or proceeding detail; grade 1 for general transmission-need discussion; grade 0 for power matters with no transmission-line angle.

### q38: natural gas pipeline capacity expansion
A relevant document discusses natural gas pipeline capacity or expansion serving power generation or industrial load; grade 2 for a specific pipeline project or capacity agreement; grade 1 for general gas-supply discussion; grade 0 for pipeline matters unrelated to power/industrial load.

### q39: gas peaker plant proposal
A relevant document discusses proposing, permitting, or opposing gas-fired peaking or backup generation plants; grade 2 for a specific plant with site, capacity, or proceeding; grade 1 for general peaker/reliability debate; grade 0 for generation matters with no gas-plant angle.

### q40: battery energy storage siting
A relevant document discusses battery energy storage systems — siting, safety, permitting, or interconnection; grade 2 for a specific BESS project or adopted standard; grade 1 for general storage discussion; grade 0 for energy matters with no storage angle.

### q41: solar farm adjacent data center
A relevant document discusses utility-scale solar projects in connection with data-center demand or co-located development; grade 2 for a specific solar project with capacity, site, or decision tied to serving load; grade 1 for general solar-for-data-centers discussion; grade 0 for solar matters with no data-center connection.

### q42: dark sky lighting ordinance industrial
A relevant document discusses outdoor lighting standards, dark-sky ordinances, or glare complaints involving industrial/data-center facilities; grade 2 for specific standards adopted or applied to a project; grade 1 for general lighting concerns; grade 0 for lighting matters unrelated to industrial uses.

### q43: viewshed historic district industrial impact
A relevant document discusses visual/viewshed impacts of industrial or data-center development on historic districts, parks, or scenic areas; grade 2 for a specific project's viewshed analysis, condition, or fight; grade 1 for general character/viewshed concerns; grade 0 for aesthetic matters with no industrial-development tie.

### q44: farmland preservation conflict development
A relevant document discusses loss of farmland or agricultural-preservation conflict with industrial/data-center development; grade 2 for a specific parcel/case where farmland conversion is contested or decided; grade 1 for general farmland-loss concern; grade 0 for agricultural matters with no development conflict.

### q45: conservation easement industrial boundary
A relevant document discusses conservation easements or protected land adjacent to or affected by industrial development; grade 2 for a specific easement or protected parcel in play; grade 1 for general open-space preservation discussion; grade 0 for easements with no development connection.

### q46: decommissioning bond surety requirements
A relevant document discusses decommissioning, reclamation, or surety/bond requirements for data centers or energy facilities; grade 2 for specific bond amounts, conditions, or adopted requirements; grade 1 for calls to require decommissioning plans; grade 0 for bonds unrelated to facility decommissioning.

### q47: fire EMS service capacity industrial facility
A relevant document discusses fire/EMS response capacity, training, or equipment needs for industrial or data-center facilities; grade 2 for specific service impacts, staffing/equipment decisions, or facility-driven needs; grade 1 for general emergency-service strain discussion; grade 0 for fire/EMS matters with no facility tie.

### q48: data center jobs promised construction operations
A relevant document discusses employment claims for data centers — construction versus permanent jobs, wages, or hiring commitments; grade 2 for specific job numbers or commitments on record for a project; grade 1 for general jobs-benefit claims or skepticism; grade 0 for employment discussion unrelated to data centers.

### q49: workforce training partnership community college
A relevant document discusses workforce development, training programs, or education partnerships tied to data-center/technology employers; grade 2 for a specific program, partnership, or funding commitment; grade 1 for general workforce-readiness discussion; grade 0 for education matters with no industry tie.

### q50: community benefit agreement developer
A relevant document discusses negotiated community benefits from a data-center/industrial developer (funds, amenities, commitments beyond proffers); grade 2 for a specific agreement or commitment with terms; grade 1 for calls to negotiate benefits; grade 0 for community programs with no developer connection.

### q51: water rate increase industrial customer
A relevant document discusses water/sewer rates or cost allocation involving large industrial customers; grade 2 for a specific rate action, tariff class, or allocation decision touching industrial users; grade 1 for general rate-impact discussion; grade 0 for rate matters with no industrial-customer angle. (Distinct from q15, which is electric rates.)

### q52: utility franchise agreement renewal
A relevant document discusses utility franchise agreements, renewals, or terms between a locality and a utility; grade 2 for specific agreement terms, negotiations, or votes; grade 1 for general franchise-authority discussion; grade 0 for utility matters with no franchise angle.

### q53: undergrounding power lines cost
A relevant document discusses burying/undergrounding power lines — costs, feasibility, or demands in siting fights; grade 2 for specific undergrounding proposals with costs or decisions; grade 1 for general undergrounding requests; grade 0 for power-line matters with no undergrounding angle.

### q54: broadband grant award county
A relevant document discusses broadband/connectivity grants or public funding awards to localities or providers; grade 2 for a specific award with amount, provider, or coverage; grade 1 for general funding-pursuit discussion; grade 0 for grants unrelated to connectivity. (Distinct from q14's buildout focus: this one is the money.)

### q55: economic development authority bond issuance
A relevant document discusses an economic development authority/IDA issuing bonds or conduit financing for industrial/tech projects; grade 2 for a specific issuance with amount, purpose, or approval; grade 1 for general EDA financing discussion; grade 0 for bonds unrelated to industrial/tech development.

### q56: industrial park infrastructure funding
A relevant document discusses publicly funded infrastructure (utilities, roads, pads) for industrial or technology parks; grade 2 for specific projects with funding sources and amounts or decisions; grade 1 for general site-readiness discussion; grade 0 for infrastructure with no industrial-park tie.

### q57: timeline slipped construction delay project
A relevant document discusses a data-center, energy, or infrastructure project falling behind schedule; grade 2 for a specific project with original versus revised dates or an acknowledged delay; grade 1 for general schedule-risk discussion; grade 0 for delays on unrelated project types.

### q58: erosion sediment control violation
A relevant document discusses erosion/sediment control compliance or violations at construction sites; grade 2 for a specific violation, stop-work order, or enforcement at an identifiable site; grade 1 for general E&S program discussion; grade 0 for environmental enforcement unrelated to construction.

### q59: zoning enforcement violation industrial
A relevant document discusses zoning or condition violations by industrial/data-center operators and enforcement responses; grade 2 for a specific violation and action (notice, fine, hearing); grade 1 for general compliance concerns; grade 0 for enforcement on unrelated uses.

### q60: conditional use permit renewal expansion
A relevant document discusses renewing, amending, or expanding an existing industrial/data-center use permit or approval; grade 2 for a specific renewal/expansion case with a decision or conditions; grade 1 for general discussion of expansion pressure; grade 0 for permit matters on unrelated uses.

### q61: electric utility capital expenditure load growth
A relevant document discusses an electric utility's capital spending or rate-base investment driven by load growth; grade 2 for specific capex figures, filings, or projects attributed to demand growth; grade 1 for general grid-investment discussion; grade 0 for utility matters with no capex/load angle. (Distinct from q10, which is AI-company capex.)

### q62: data center construction backlog contracted
A relevant document discusses contracted backlog, signed leases, or committed pipeline for data-center construction/capacity; grade 2 for backlog figures, contract values, or committed megawatts; grade 1 for general demand-pipeline talk; grade 0 for backlog discussion unrelated to data centers.

### q63: GPU purchase commitments supply agreements
A relevant document discusses purchases, supply agreements, or allocation of AI accelerators/GPUs; grade 2 for specific quantities, dollar commitments, or named supply agreements; grade 1 for general chip-supply discussion; grade 0 for hardware matters with no accelerator-procurement angle.

### q64: server depreciation useful life change
A relevant document discusses depreciation policy or useful-life estimates for servers/computing equipment; grade 2 for a specific accounting change with years or dollar impact; grade 1 for general depreciation discussion of tech assets; grade 0 for depreciation of unrelated asset classes.

### q65: lease versus own data center strategy
A relevant document discusses leasing versus owning/building data-center capacity as a strategy or cost decision; grade 2 for specific strategy statements with capacity, costs, or shifts disclosed; grade 1 for general make-versus-buy discussion; grade 0 for real-estate strategy unrelated to data centers.

### q66: hyperscaler preleasing demand disclosure
A relevant document discusses preleasing, anchor tenants, or hyperscaler demand commitments for data-center capacity; grade 2 for specific prelease percentages, tenants, or committed capacity; grade 1 for general demand-strength claims; grade 0 for leasing discussion unrelated to data centers.

### q67: data center vacancy rates market
A relevant document discusses data-center vacancy, absorption, or supply-demand balance in a market; grade 2 for specific vacancy/absorption figures or named-market conditions; grade 1 for general tight-market claims; grade 0 for real-estate metrics unrelated to data centers.

### q68: renewable power purchase agreement data center
A relevant document discusses renewable PPAs or clean-energy procurement for data-center load; grade 2 for a specific PPA with counterparty, capacity, or term; grade 1 for general clean-procurement claims; grade 0 for renewables discussion with no procurement/load tie.

### q69: transformer supply chain shortage
A relevant document discusses shortages or long lead times for transformers, switchgear, or grid equipment; grade 2 for specific lead times, costs, or named impacts on projects; grade 1 for general equipment-shortage discussion; grade 0 for supply-chain matters unrelated to grid equipment.

### q70: liquid cooling technology adoption
A relevant document discusses liquid/immersion cooling or cooling-technology transitions in data centers; grade 2 for specific deployments, capacity, or capex tied to cooling changes; grade 1 for general cooling-trend discussion; grade 0 for cooling matters unrelated to data centers.

### q71: electricity cost margin impact
A relevant document discusses electricity/power costs affecting operating margins or unit economics of data-center or AI businesses; grade 2 for quantified cost impacts, hedges, or margin effects; grade 1 for general power-cost concern; grade 0 for cost discussion with no power angle.

### q72: debt financing data center construction
A relevant document discusses debt raised to finance data-center or AI-infrastructure buildout — notes, credit facilities, securitizations; grade 2 for specific instruments with amounts, rates, or terms; grade 1 for general leverage/financing-needs discussion; grade 0 for debt unrelated to infrastructure buildout.

### q73: GPU backed loan collateral
A relevant document discusses loans collateralized by GPUs/compute or compute-backed financing structures; grade 2 for specific facilities with amounts, collateral terms, or lenders; grade 1 for general discussion of chips as collateral; grade 0 for lending with no compute-collateral angle.

### q74: customer concentration risk cloud
A relevant document discusses revenue concentration in few customers for cloud/AI-infrastructure companies; grade 2 for disclosed percentages or named-customer dependence; grade 1 for general concentration-risk language; grade 0 for customer discussion with no concentration angle.

### q75: impairment charge data center assets
A relevant document discusses impairments, write-downs, or abandonments of data-center or compute assets; grade 2 for specific charges with amounts and causes; grade 1 for impairment-risk discussion; grade 0 for impairments of unrelated assets.

### q76: energy hedging strategy disclosure
A relevant document discusses hedging power/energy price exposure — contracts, derivatives, or fixed-price arrangements; grade 2 for specific hedge positions, volumes, or accounting; grade 1 for general hedging-approach statements; grade 0 for hedging of non-energy exposures.

### q77: water usage sustainability disclosure
A relevant document contains corporate disclosure of water usage, WUE, or water-stewardship commitments for data centers; grade 2 for quantified usage/efficiency figures or concrete commitments; grade 1 for general water-sustainability claims; grade 0 for sustainability content with no water specifics. (Distinct from q1/q12's civic angles: this is issuer disclosure.)

### q78: renewable energy credits carbon neutral claims
A relevant document discusses RECs, carbon offsets, or carbon-neutrality/net-zero claims tied to data-center operations; grade 2 for specific quantities, purchases, or audited claims; grade 1 for general green-claims discussion; grade 0 for climate content with no credits/claims angle.

### q79: construction labor shortage disclosure
A relevant document discusses skilled-labor shortages (electricians, trades) affecting data-center or energy construction; grade 2 for specific impacts on schedules/costs or named projects; grade 1 for general labor-market tightness; grade 0 for labor matters unrelated to construction.

### q80: permitting delay risk factor
A relevant document discusses permitting or approval timelines as a risk or constraint on data-center/energy buildout; grade 2 for specific delays, timelines, or named stalled projects; grade 1 for generic permitting-risk language; grade 0 for risk discussion with no permitting angle.

### q81: related party transaction data center
A relevant document discusses related-party or affiliate transactions involving data-center/AI-infrastructure companies; grade 2 for specific transactions with parties and amounts; grade 1 for general related-party disclosure; grade 0 for transactions with no related-party angle.

### q82: remaining performance obligations cloud growth
A relevant document discusses remaining performance obligations, deferred revenue, or contracted future revenue for cloud/AI services; grade 2 for specific RPO figures or growth rates; grade 1 for general contracted-revenue discussion; grade 0 for revenue metrics with no forward-obligation angle.

### q83: colocation pricing escalators rate increases
A relevant document discusses colocation/data-center pricing power, rate escalators, or renewal spreads; grade 2 for specific pricing figures, escalator terms, or renewal-rate changes; grade 1 for general pricing-strength claims; grade 0 for pricing discussion unrelated to data-center services.

### q84: international data center expansion
A relevant document discusses data-center expansion outside the US — new regions, countries, or sovereign-cloud commitments; grade 2 for specific locations, capacity, or investment amounts; grade 1 for general global-expansion strategy; grade 0 for international operations with no data-center angle.

### q85: edge computing deployment plans
A relevant document discusses edge data centers or distributed compute deployments; grade 2 for specific deployments, counts, or investments; grade 1 for general edge-strategy discussion; grade 0 for computing topics with no edge-deployment angle.

### q86: promised tax revenue delivered actual
A relevant document compares promised/projected data-center fiscal benefits against actual results, or audits such claims; grade 2 for concrete promised-versus-actual figures or an official accounting; grade 1 for skepticism or demands to verify benefit claims; grade 0 for fiscal discussion with no promise-versus-actual angle.

### q87: noise mitigation promised compliance follow up
A relevant document discusses whether promised noise mitigation was implemented or is working — follow-up complaints, monitoring results, or enforcement after commitments; grade 2 for a specific facility's post-commitment compliance record; grade 1 for general doubts about mitigation effectiveness; grade 0 for noise matters with no commitment-follow-up angle. (Distinct from q6's initial complaints.)

### q88: water usage cap limit agreement compliance
A relevant document discusses negotiated water-usage caps/limits for a facility and adherence to them; grade 2 for specific limits with volumes and any compliance reporting; grade 1 for calls to impose usage limits; grade 0 for water matters with no cap/limit angle.

### q89: megawatt capacity announced project
A relevant document announces or specifies the power capacity (MW/GW) of a data-center project or campus; grade 2 for specific capacity figures tied to a named project/site; grade 1 for general scale claims without figures; grade 0 for capacity discussion unrelated to data centers.

### q90: land banking speculative acquisition data center
A relevant document discusses speculative land assembly or banking for future data-center development; grade 2 for specific acquisitions with acreage/price and a data-center purpose stated or inferred on record; grade 1 for general land-rush discussion; grade 0 for land transactions with no data-center speculation angle. (Distinct from q13's transaction focus: this is the speculative-assembly pattern.)

### q91: moratorium outcome study results adopted
A relevant document discusses what came out of a data-center pause/study — findings, adopted recommendations, or lifted/extended moratoria; grade 2 for specific study results or post-moratorium actions with decisions; grade 1 for status updates on ongoing studies; grade 0 for moratorium content with no outcome angle. (Distinct from q7's imposition focus.)

### q92: county budget data center revenue dependence
A relevant document discusses a locality's budget reliance on data-center revenue — share of revenue, volatility risk, or diversification; grade 2 for specific percentages/amounts or adopted budget decisions reflecting that reliance; grade 1 for general dependence concerns; grade 0 for budget matters with no data-center-revenue angle.

### q93: electric grid reliability concerns residents
A relevant document contains resident or official concerns about grid reliability, outages, or capacity strain attributed to large new loads; grade 2 for specific reliability events, studies, or official findings tied to load growth; grade 1 for general reliability worry; grade 0 for outage/reliability talk with no large-load connection.

### q94: crypto mining conversion AI data center
A relevant document discusses converting cryptocurrency-mining facilities or sites to AI/HPC data-center use; grade 2 for a specific conversion with site, capacity, or economics; grade 1 for general pivot-strategy discussion; grade 0 for crypto or AI content with no conversion angle.

### q95: neocloud capacity contract announcement
A relevant document announces or details a neocloud/GPU-cloud capacity contract, customer win, or capacity commitment; grade 2 for specific contract values, capacity, or counterparties; grade 1 for general growth/bookings claims; grade 0 for cloud announcements with no capacity-contract angle.

### q96: municipal water supply contract industrial
A relevant document discusses a water-supply agreement between a public system and an industrial/data-center customer; grade 2 for specific contract volumes, rates, or approvals; grade 1 for general large-user supply discussion; grade 0 for water contracts with no industrial-customer angle.

### q97: historic battlefield adjacent development
A relevant document discusses industrial/data-center development near battlefields, historic sites, or cemeteries; grade 2 for a specific project-versus-site conflict with positions or decisions on record; grade 1 for general historic-resource concerns; grade 0 for historic matters with no development conflict.

### q98: data center campus master plan phases
A relevant document discusses multi-building data-center campus plans — phasing, total buildout, or master-plan approvals; grade 2 for specific phase counts, square footage/MW, or plan approvals; grade 1 for general campus-scale discussion; grade 0 for site plans unrelated to data centers.

### q99: school adjacent data center concerns
A relevant document discusses data-center projects near schools or residential-institutional uses and the resulting concerns (noise, traffic, safety, siting); grade 2 for a specific project-near-school case with testimony or decisions; grade 1 for general compatibility concerns; grade 0 for school matters with no data-center proximity angle.

### q100: climate resilience extreme heat cooling demand
A relevant document discusses extreme heat, drought, or climate stress interacting with data-center cooling or power demand; grade 2 for specific events, curtailments, or resilience measures tied to facilities; grade 1 for general climate-strain discussion; grade 0 for climate content with no facility-demand angle.
