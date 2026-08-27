import { Outlet, ScrollRestoration } from "react-router-dom";

function App() {
  return (
    <>
      <ScrollRestoration />
      <Outlet />
    </>
  );
}

export default App;
