import { AppProvider, useApp } from './lib/app'
import { useManifest } from './lib/data'
import { Overlays, ProgressPanel, SidebarExpander } from './lib/menus'
import { s } from './lib/style'
import { MarketOverviewScreen } from './screens/MarketOverview'
import { MarketDataScreen } from './screens/MarketData'
import { PolicyDeepDiveScreen } from './screens/PolicyDeepDive'
import { CapacityAuctionsScreen } from './screens/CapacityAuctions'

const ROOT =
  "display:flex;height:100vh;min-width:1280px;background:var(--bg0);font-family:'Inter','Noto Sans JP','Hiragino Kaku Gothic ProN','Yu Gothic',system-ui,sans-serif;color:var(--tx);font-size:14px;line-height:1.5;overflow:hidden;position:relative"

// Toast markup ported from the exports (position switched to fixed for the
// global overlay): bottom-right pill with a teal left border.
// z-index must beat the modal backdrop (200) — most toasts are fired from inside
// a modal, and under it they read as "nothing happened".
const TOAST =
  'position:fixed;bottom:24px;right:24px;background:var(--bg1);border-left:3px solid var(--ac);border-radius:12px;box-shadow:var(--sh2a);padding:12px 18px;font-size:13px;color:var(--tx);z-index:300;max-width:420px'

function CurrentScreen() {
  const { screen } = useApp()
  switch (screen) {
    case 'market':
      return <MarketDataScreen />
    case 'policy':
      return <PolicyDeepDiveScreen />
    case 'capacity':
      return <CapacityAuctionsScreen />
    default:
      return <MarketOverviewScreen />
  }
}

function Toast() {
  const { toastMsg } = useApp()
  if (!toastMsg) return null
  return <div style={s(TOAST)}>{toastMsg}</div>
}

const UNAVAILABLE =
  'position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:260;background-color:var(--bg1);background-image:linear-gradient(var(--warnBg),var(--warnBg));border:1px solid var(--warnTx);border-radius:12px;padding:9px 16px;font-size:12.5px;font-weight:600;color:var(--warnTx);box-shadow:var(--sh2a);max-width:640px'

// Every screen falls back to built-in sample data, which looks real; say so when there is no export.
function DataUnavailable() {
  const { lang } = useApp()
  const { error } = useManifest()
  if (!error) return null
  return (
    <div role="alert" style={s(UNAVAILABLE)}>
      {lang === 'ja'
        ? 'データを読み込めませんでした — 表示中の数値はサンプルです。実際の市場データではありません。'
        : 'Market data could not be loaded — the figures shown are sample data, not real market data.'}
    </div>
  )
}

function Root() {
  const { theme } = useApp()
  return (
    <div
      data-jema-root="1"
      data-dark={theme === 'dark' ? 'true' : 'false'}
      style={s(ROOT)}
    >
      <CurrentScreen />
      <SidebarExpander />
      <DataUnavailable />
      <Overlays />
      <ProgressPanel />
      <Toast />
    </div>
  )
}

export function App() {
  return (
    <AppProvider>
      <Root />
    </AppProvider>
  )
}
