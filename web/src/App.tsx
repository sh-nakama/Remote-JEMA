import { AppProvider, useApp } from './lib/app'
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
const TOAST =
  'position:fixed;bottom:24px;right:24px;background:var(--bg1);border-left:3px solid var(--ac);border-radius:12px;box-shadow:var(--sh2a);padding:12px 18px;font-size:13px;color:var(--tx);z-index:100;max-width:420px'

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
