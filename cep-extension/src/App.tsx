import { MCPControlPanel } from "./components/MCPControlPanel";

export default function App() {
  return (
    <div style={{
      width: '100%',
      height: '100vh',
      backgroundColor: '#000',
      overflow: 'hidden',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif',
    }}>
      <MCPControlPanel />
    </div>
  );
}
