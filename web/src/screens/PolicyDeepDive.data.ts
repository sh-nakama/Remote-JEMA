// Fixture data ported from screens/policy-deep-dive.html (DCLogic constructor).

export interface Committee {
  key: string
  org: 'METI' | 'OCCTO' | 'EGC'
  en: string
  ja: string
  tier: string
  followed: boolean
  last: string
  nextNo?: number
  nextDate?: string
}

export interface DigestSection {
  h: string
  items: string[]
}

export interface JpSection {
  h: string
  t: string
}

export interface DocRef {
  name: string
  size: string
}

export interface Meeting {
  key: string
  com?: string
  org?: string
  untracked?: boolean
  en: string
  ja: string
  date: string
  status: string
  tori?: boolean
  prevEn?: string
  prevJa?: string
  title: string
  titleJa: string
  sub: string
  digest?: DigestSection[]
  jp?: JpSection[]
  refs?: string[]
  emptyTitle?: string
  emptySub?: string
  docs: DocRef[]
}

export interface Upcoming {
  key: string
  com: string
  status: string
  prevKey: string
  en: string
  ja: string
  date: string
  title: string
  titleJa: string
  sub: string
  prevEn: string
  prevJa: string
  agendaEn: string[]
  agendaJa: string[]
  docs: DocRef[]
}

export const committees: Committee[] = [
  { key: 'basic', org: 'METI', en: 'E&G Basic Policy Subcommittee', ja: '電力・ガス基本政策小委員会', tier: 'Tier 1', followed: true, last: '第84回 · 5d', nextNo: 85, nextDate: '2026-08-05' },
  { key: 'sysrev', org: 'METI', en: 'System Review WG', ja: '制度検討作業部会', tier: 'Tier 1', followed: true, last: '第60回 · 13d', nextNo: 61, nextDate: '2026-07-10' },
  { key: 'renew', org: 'METI', en: 'Renewable Integration & Next-gen Grid', ja: '再エネ大量導入・次世代NW小委', tier: 'Tier 2', followed: true, last: '第63回 · 27d' },
  { key: 'emis', org: 'METI', en: 'Emissions Trading WG', ja: '排出量取引制度WG', tier: 'Tier 2', followed: false, last: '第14回 · 27d' },
  { key: 'supply', org: 'OCCTO', en: 'Mid- & Long-term Power Supply WG', ja: '中長期の供給力確保WG', tier: 'Tier 2', followed: false, last: '第12回 · 13d' },
  { key: 'balrev', org: 'OCCTO', en: 'Balancing Market Review Subcommittee', ja: '需給調整市場検討小委員会', tier: 'Tier 2', followed: false, last: '第47回 · 22d', nextNo: 48, nextDate: '2026-07-17' },
  { key: 'egmsc', org: 'EGC', en: 'E&G Market Surveillance Commission', ja: '電力・ガス取引監視等委員会', tier: 'Tier 1', followed: true, last: '第58回 · 8d', nextNo: 59, nextDate: '2026-07-22' },
  { key: 'inst', org: 'EGC', en: 'Institutional Design Subcommittee', ja: '制度設計専門会合', tier: 'Tier 1', followed: true, last: '第91回 · 19d' },
]

export const meetings: Meeting[] = [
  {
    key: 'basic84', com: 'basic', en: 'Basic Policy · No. 84', ja: '基本政策小委 · 第84回', date: '2026-06-27', status: 'done', tori: false,
    prevEn: 'Debated capacity-market linkage for long-duration storage; secretariat to draft options for August.',
    prevJa: '長期蓄電池の容量市場連携を審議。8月会合に向け事務局が選択肢を整理へ。',
    title: 'E&G Basic Policy Subcommittee — No. 84', titleJa: '電力・ガス基本政策小委員会 第84回',
    sub: '電力・ガス基本政策小委員会 · 2026-06-27 · METI · 議事録 · Summarised 06-29',
    digest: [
      { h: 'Key decisions', items: ['Agreed to study explicit capacity-market linkage for long-duration storage (8h+), with eligibility criteria to be drafted by the secretariat.', 'Confirmed the FY2027 review timeline for the kWh-market monitoring framework.'] },
      { h: 'Points of discussion', items: ['Committee members split on whether linkage should extend to pumped hydro refurbishments or new-build batteries only.', 'Consumer representatives raised cost-recovery transparency concerns for pass-through to retail tariffs.'] },
      { h: 'Action items', items: ['Secretariat to present 3 design options at the August meeting (No. 85).', 'OCCTO to provide LTDA auction interaction analysis by end of July.'] },
    ],
    jp: [
      { h: '主要な論点', t: '長期蓄電池（8時間超）の容量市場連携の要否と適格性基準。揚水改修を含めるか新設蓄電池に限定するかで意見が分かれた。' },
      { h: '主要な数値', t: '対象候補容量 約4.2GW（事務局推計）。FY2027制度見直しまでに詳細設計を確定する工程を確認。' },
      { h: '結論', t: '事務局が8月の第85回会合で3つの設計オプションを提示することで合意。' },
      { h: '今後の課題', t: 'LTDAオークションとの相互作用分析（OCCTO、7月末まで）。小売料金への転嫁透明性の確保策。' },
    ],
    refs: ['資料3 · pp.12-18', '資料4 · p.6', '議事要旨 · p.2'],
    docs: [{ name: '資料1_議事次第.pdf', size: '0.2 MB' }, { name: '資料3_長期蓄電池と容量市場.pdf', size: '4.8 MB' }, { name: '資料4_モニタリング枠組み.pdf', size: '2.1 MB' }],
  },
  {
    key: 'egmsc58', com: 'egmsc', en: 'EGMSC · No. 58', ja: '監視等委 · 第58回', date: '2026-06-24', status: 'done', tori: true,
    prevEn: 'Adopted the interim report on the wheeling-charge review; FY2027 tariff-reform framework now fixed.',
    prevJa: '託送料金制度見直しの中間とりまとめを採択。FY2027の料金改革枠組みが確定。',
    title: 'E&G Market Surveillance Commission — No. 58', titleJa: '電力・ガス取引監視等委員会 第58回',
    sub: '電力・ガス取引監視等委員会 · 2026-06-24 · EGC · とりまとめ · 議事録 · Summarised 06-26',
    digest: [
      { h: 'Key decisions', items: ['Adopted the interim report (中間とりまとめ) on the wheeling-charge review — the FY2027 tariff-reform framework is now fixed.', 'Approved revised information-disclosure guidelines for general transmission & distribution utilities.'] },
      { h: 'Points of discussion', items: ['Extent to which revenue-cap incentives should reward proactive grid reinforcement versus cost minimisation.', 'Treatment of EV-charging demand forecasts in the next regulatory period’s demand assumptions.'] },
      { h: 'Action items', items: ['Secretariat to publish the final report draft for public comment in July.', 'GT&D utilities to file revised FY2027 revenue-cap applications by September.'] },
    ],
    jp: [
      { h: '主要な論点', t: '託送料金制度見直しの中間とりまとめ採択。レベニューキャップ制度の第2規制期間に向けたインセンティブ設計、系統増強への先行投資評価。' },
      { h: '主要な数値', t: '第2規制期間はFY2028〜FY2032。公共コメントは7月中旬から30日間を予定。' },
      { h: '結論', t: '中間とりまとめを全会一致で採択。FY2027料金改革の枠組みが確定した。' },
      { h: '今後の課題', t: '最終報告書案の公表とパブコメ対応。一般送配電事業者のレベニューキャップ申請（9月期限）の審査体制整備。' },
    ],
    refs: ['資料2 · pp.4-9', '資料3 · pp.22-31', 'とりまとめ本文 · p.14'],
    docs: [{ name: '資料1_議事次第.pdf', size: '0.2 MB' }, { name: '資料2_中間とりまとめ（案）.pdf', size: '6.3 MB' }, { name: '資料3_託送料金制度の見直し.pdf', size: '5.1 MB' }, { name: '議事要旨.pdf', size: '0.4 MB' }],
  },
  {
    key: 'sysrev60', com: 'sysrev', en: 'System Review WG · No. 60', ja: '制度検討WG · 第60回', date: '2026-06-19', status: 'running', tori: false,
    prevEn: 'Materials ingested · summarisation in progress (2 of 6 documents done).',
    prevJa: '資料取得済み · 要約処理中（6件中2件完了）。',
    title: 'System Review WG — No. 60', titleJa: '制度検討作業部会 第60回',
    sub: '制度検討作業部会 · 2026-06-19 · METI · Summarising… 要約処理中',
    emptyTitle: 'Summarisation in progress · 要約処理中',
    emptySub: '2 of 6 documents processed · started 06:12 JST · ETA ~4 min',
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_同時市場の詳細設計.pdf', size: '7.9 MB' }, { name: '資料3_三次調整力の調達.pdf', size: '3.3 MB' }],
  },
  {
    key: 'inst91', com: 'inst', en: 'Inst. Design · No. 91', ja: '制度設計専門会合 · 第91回', date: '2026-06-13', status: 'done', tori: false,
    prevEn: 'Discussed imbalance-penalty recalibration and EPRX bidding-guideline amendments for tertiary products.',
    prevJa: 'インバランス料金の再調整と三次調整力の入札ガイドライン改定を議論。',
    title: 'Institutional Design Subcommittee — No. 91', titleJa: '制度設計専門会合 第91回',
    sub: '制度設計専門会合 · 2026-06-13 · EGC · 議事録 · Summarised 06-16',
    digest: [
      { h: 'Key decisions', items: ['Endorsed recalibrating the imbalance-price cap parameters K and L from FY2027, subject to public comment.', 'Approved EPRX bidding-guideline amendments tightening offer-curve granularity for tertiary② products.'] },
      { h: 'Points of discussion', items: ['Whether the current ¥600/kWh scarcity cap distorts BG hedging incentives during tight supply.', 'Aggregators requested a transition period for the new tertiary bidding format.'] },
      { h: 'Action items', items: ['Secretariat to run parameter simulations against FY2025 tight-supply days and report at No. 92.'] },
    ],
    jp: [
      { h: '主要な論点', t: 'インバランス料金のK・Lパラメータ再調整、三次調整力②の入札ガイドライン改定、¥600/kWh上限の妥当性。' },
      { h: '主要な数値', t: 'FY2025の需給ひっ迫日（12日間）を対象にシミュレーション実施予定。新入札様式の経過措置は6ヶ月案。' },
      { h: '結論', t: 'FY2027からのパラメータ再調整方針を了承（パブコメ付き）。ガイドライン改定を承認。' },
      { h: '今後の課題', t: '第92回でのシミュレーション結果報告。アグリゲーター向け経過措置の詳細設計。' },
    ],
    refs: ['資料4 · pp.8-15', '資料5 · p.3'],
    docs: [{ name: '資料4_インバランス料金の見直し.pdf', size: '3.7 MB' }, { name: '資料5_需給調整市場ガイドライン改定.pdf', size: '2.9 MB' }],
  },
  {
    key: 'balrev47', com: 'balrev', en: 'Balancing Mkt Review · No. 47', ja: '需給調整市場検討小委 · 第47回', date: '2026-06-10', status: 'pending', tori: false,
    title: 'Balancing Market Review Subcommittee — No. 47', titleJa: '需給調整市場検討小委員会 第47回',
    sub: '需給調整市場検討小委員会 · 2026-06-10 · OCCTO · Pending · Queued',
    emptyTitle: 'Summary pending · 要約待ち',
    emptySub: 'Queued behind 2 jobs · materials detected 06-11 · will run on next catch-up',
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_調達実績の評価.pdf', size: '5.5 MB' }],
  },
  {
    key: 'renew63', com: 'renew', en: 'Renewable Integration · No. 63', ja: '再エネ大量導入小委 · 第63回', date: '2026-06-05', status: 'done', tori: false,
    prevEn: 'Progress check on non-firm connection expansion and curtailment forecasting accuracy.',
    prevJa: 'ノンファーム接続拡大と出力制御予測の精度を確認。',
    title: 'Renewable Integration & Next-gen Grid — No. 63', titleJa: '再エネ大量導入・次世代電力NW小委員会 第63回',
    sub: '再エネ大量導入・次世代電力NW小委員会 · 2026-06-05 · METI · 議事録 · Summarised 06-08',
    digest: [
      { h: 'Key decisions', items: ['Confirmed nationwide rollout of non-firm connection to all local (77kV-class) grids from FY2027.', 'Adopted new accuracy KPIs for day-ahead curtailment forecasts (MAE targets per area).'] },
      { h: 'Points of discussion', items: ['Kyushu curtailment rates remain elevated (spring midday); storage co-location incentives debated.'] },
      { h: 'Action items', items: ['OCCTO to publish per-area curtailment forecast scorecards quarterly from October.'] },
    ],
    jp: [
      { h: '主要な論点', t: 'ローカル系統へのノンファーム接続全国展開、出力制御の前日予測精度KPI、九州の春季昼間の制御率。' },
      { h: '主要な数値', t: 'FY2027から77kV級系統に展開。九州の春季出力制御率は約6.8%（前年比 −0.9pt）。' },
      { h: '結論', t: 'ノンファーム接続の全国展開方針とKPI導入を確認。' },
      { h: '今後の課題', t: '併設蓄電池インセンティブの制度設計。四半期スコアカードの公表体制（10月開始）。' },
    ],
    refs: ['資料2 · pp.5-11', '資料3 · p.19'],
    docs: [{ name: '資料2_ノンファーム接続の展開.pdf', size: '4.2 MB' }, { name: '資料3_出力制御の実績と見通し.pdf', size: '6.0 MB' }],
  },
  {
    key: 'emis14', com: 'emis', en: 'Emissions Trading WG · No. 14', ja: '排出量取引WG · 第14回', date: '2026-06-05', status: 'failed', tori: false,
    title: 'Emissions Trading WG — No. 14', titleJa: '排出量取引制度WG 第14回',
    sub: '排出量取引制度WG · 2026-06-05 · METI · Failed — retry · quality: OCR',
    emptyTitle: 'Summarisation failed · 要約失敗',
    emptySub: 'Scanned PDF failed OCR quality gate (confidence 0.61 < 0.75) · 2 attempts',
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_制度骨格（スキャン）.pdf', size: '11.4 MB' }],
  },
]

// Untracked METI meetings — full coverage, searchable, summaries queue to NotebookLM on track
export const untracked: Meeting[] = [
  {
    key: 'hyd22', org: 'METI', untracked: true, en: 'Hydrogen & Ammonia Policy · No. 22', ja: '水素・アンモニア政策小委 · 第22回', date: '2026-06-30', status: 'untracked',
    title: 'Hydrogen & Ammonia Policy Subcommittee — No. 22', titleJa: '水素・アンモニア政策小委員会 第22回',
    sub: '水素・アンモニア政策小委員会 · 2026-06-30 · METI · untracked 未追跡',
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_価格差支援（CfD）の進捗.pdf', size: '3.6 MB' }],
  },
  {
    key: 'nuc45', org: 'METI', untracked: true, en: 'Nuclear Subcommittee · No. 45', ja: '原子力小委員会 · 第45回', date: '2026-06-26', status: 'untracked',
    title: 'Nuclear Subcommittee — No. 45', titleJa: '原子力小委員会 第45回',
    sub: '原子力小委員会 · 2026-06-26 · METI · untracked 未追跡',
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料3_次世代革新炉の開発状況.pdf', size: '8.2 MB' }],
  },
  {
    key: 'ene38', org: 'METI', untracked: true, en: 'Energy Efficiency Subcommittee · No. 38', ja: '省エネルギー小委員会 · 第38回', date: '2026-06-18', status: 'untracked',
    title: 'Energy Efficiency Subcommittee — No. 38', titleJa: '省エネルギー小委員会 第38回',
    sub: '省エネルギー小委員会 · 2026-06-18 · METI · untracked 未追跡',
    docs: [{ name: '資料2_ベンチマーク制度の見直し.pdf', size: '2.4 MB' }],
  },
  {
    key: 'cp9', org: 'METI', untracked: true, en: 'Carbon Pricing Expert WG · No. 9', ja: 'カーボンプライシング専門WG · 第9回', date: '2026-06-16', status: 'untracked',
    title: 'Carbon Pricing Expert WG — No. 9', titleJa: 'カーボンプライシング専門WG 第9回',
    sub: 'カーボンプライシング専門WG · 2026-06-16 · METI · untracked 未追跡',
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_有償オークションの設計論点.pdf', size: '4.9 MB' }],
  },
  {
    key: 'bat11', org: 'METI', untracked: true, en: 'Battery Industry Strategy Council · No. 11', ja: '蓄電池産業戦略検討官民協議会 · 第11回', date: '2026-06-09', status: 'untracked',
    title: 'Battery Industry Strategy Council — No. 11', titleJa: '蓄電池産業戦略検討官民協議会 第11回',
    sub: '蓄電池産業戦略検討官民協議会 · 2026-06-09 · METI · untracked 未追跡',
    docs: [{ name: '資料3_国内製造基盤の投資動向.pdf', size: '5.7 MB' }],
  },
  {
    key: 'osw31', org: 'METI', untracked: true, en: 'Offshore Wind Promotion WG · No. 31', ja: '洋上風力促進WG · 第31回', date: '2026-06-03', status: 'untracked',
    title: 'Offshore Wind Promotion WG — No. 31', titleJa: '洋上風力促進ワーキンググループ 第31回',
    sub: '洋上風力促進WG · 2026-06-03 · METI · untracked 未追跡',
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_ラウンド4公募の状況.pdf', size: '6.1 MB' }],
  },
]

// Scheduled upcoming meetings — agenda published, digest arrives after the meeting
export const upcoming: Upcoming[] = [
  {
    key: 'sysrev61', com: 'sysrev', status: 'scheduled', prevKey: 'sysrev60',
    en: 'System Review WG · No. 61', ja: '制度検討WG · 第61回', date: '2026-07-10',
    title: 'System Review WG — No. 61', titleJa: '制度検討作業部会 第61回',
    sub: '制度検討作業部会 · 2026-07-10 · METI · agenda published 議題公表済み',
    prevEn: 'Agenda: simultaneous-market detailed design — settlement & bidding interactions.',
    prevJa: '議題：同時市場の詳細設計 — 精算・入札の相互作用。',
    agendaEn: ['Simultaneous market (同時市場) detailed design: settlement and bidding interactions.', 'Treatment of BG imbalance positions under combined kWh/ΔkW clearing.', 'Report: FY2026 system-cost simulation — interim results.'],
    agendaJa: ['同時市場の詳細設計：精算・入札の相互作用', '同時約定におけるBGインバランスポジションの取扱い', '報告：FY2026システムコスト試算の中間結果'],
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_同時市場の詳細設計（続）.pdf', size: '5.4 MB' }],
  },
  {
    key: 'balrev48', com: 'balrev', status: 'scheduled', prevKey: 'balrev47',
    en: 'Balancing Mkt Review · No. 48', ja: '需給調整市場検討小委 · 第48回', date: '2026-07-17',
    title: 'Balancing Market Review Subcommittee — No. 48', titleJa: '需給調整市場検討小委員会 第48回',
    sub: '需給調整市場検討小委員会 · 2026-07-17 · OCCTO · agenda published 議題公表済み',
    prevEn: 'Agenda: FY2026 procurement review & tertiary② shortfall countermeasures.',
    prevJa: '議題：FY2026調達実績の点検と三次②不足対策。',
    agendaEn: ['FY2026 procurement results across the five ΔkW products.', 'Countermeasures for tertiary② evening-ramp shortfalls.', 'Aggregator participation: metering-requirement relaxation status.'],
    agendaJa: ['FY2026調達実績の点検（5商品）', '三次調整力②の夕方ランプ不足対策', 'アグリゲーター参入：計量要件緩和の状況'],
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_調達実績と不足対策.pdf', size: '4.1 MB' }],
  },
  {
    key: 'egmsc59', com: 'egmsc', status: 'scheduled', prevKey: 'egmsc58',
    en: 'EGMSC · No. 59', ja: '監視等委 · 第59回', date: '2026-07-22',
    title: 'E&G Market Surveillance Commission — No. 59', titleJa: '電力・ガス取引監視等委員会 第59回',
    sub: '電力・ガス取引監視等委員会 · 2026-07-22 · EGC · agenda published 議題公表済み',
    prevEn: 'Agenda: final wheeling-charge report put to public comment; retail-market monitoring update.',
    prevJa: '議題：託送料金最終報告案のパブコメ付議、小売市場モニタリング報告。',
    agendaEn: ['Final wheeling-charge report: put to public comment (30 days).', 'Retail-market monitoring: switching rates and offer diversity.', 'Follow-up: information-disclosure guideline compliance.'],
    agendaJa: ['託送料金最終報告案：パブリックコメント付議（30日間）', '小売市場モニタリング：スイッチング率と料金メニュー多様性', '情報開示ガイドライン遵守状況のフォローアップ'],
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料2_最終報告（案）.pdf', size: '7.2 MB' }],
  },
  {
    key: 'basic85', com: 'basic', status: 'scheduled', prevKey: 'basic84',
    en: 'Basic Policy · No. 85', ja: '基本政策小委 · 第85回', date: '2026-08-05',
    title: 'E&G Basic Policy Subcommittee — No. 85', titleJa: '電力・ガス基本政策小委員会 第85回',
    sub: '電力・ガス基本政策小委員会 · 2026-08-05 · METI · agenda published 議題公表済み',
    prevEn: 'Agenda: 3 design options for long-duration storage capacity-market linkage.',
    prevJa: '議題：長期蓄電池の容量市場連携に関する3つの設計オプション。',
    agendaEn: ['Three design options for long-duration storage capacity-market linkage.', 'LTDA Round 4 requirements: storage participation thresholds.', 'OCCTO analysis: LTDA × capacity-market interaction.'],
    agendaJa: ['長期蓄電池の容量市場連携：3つの設計オプション', '長期脱炭素オークション第4回の要件：蓄電池参入閾値', 'OCCTO分析：LTDAと容量市場の相互作用'],
    docs: [{ name: '資料1_議事次第.pdf', size: '0.1 MB' }, { name: '資料3_設計オプション比較.pdf', size: '3.9 MB' }],
  },
]
