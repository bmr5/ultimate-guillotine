import { Outlet } from "react-router-dom";

import { Nav } from "./home-page/Nav";

function App() {
  return (
    <div className="flex min-h-screen w-full flex-col bg-muted/40">
      <Nav />
      <Outlet />
    </div>
  );
}

export default App;
