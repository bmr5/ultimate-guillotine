import { Link } from "react-router-dom";

import { buttonVariants } from "@/components/ui/button";

export default function HomePage() {
  return (
    <>
      <h1>Home</h1>
      <p>
        This is the home page. It is a static page that is not part of the
        dashboard.
      </p>
      <div>
        <Link to="/dashboard" className={buttonVariants({})}>
          Go to dashboard
        </Link>
      </div>
    </>
  );
}
