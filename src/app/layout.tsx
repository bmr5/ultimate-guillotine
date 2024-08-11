import { Outlet } from "react-router-dom";

import { Nav } from "./home/Nav";

function App() {
  return (
    <div className="flex min-h-screen w-full flex-col bg-muted/40">
      <Nav />
      <div className="flex flex-col sm:gap-4 sm:py-4 sm:pl-14">
        <Outlet />
      </div>
    </div>
  );
}

export default App;
