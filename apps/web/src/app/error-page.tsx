import { isRouteErrorResponse, useRouteError } from "react-router";

export default function ErrorPage() {
  const error = useRouteError();
  console.error(error);
  const message = isRouteErrorResponse(error)
    ? error.statusText
    : error instanceof Error
      ? error.message
      : "Unknown error";

  return (
    <div id="error-page" className="mx-auto max-w-6xl px-4 py-16">
      <h1 className="text-4xl figures">The board could not load</h1>
      <p className="mt-3 max-w-prose text-muted-foreground">
        Reload the page. If it keeps happening, tell the commissioner what the
        message below says.
      </p>
      <p className="mt-4 rounded-md border bg-card px-3 py-2 text-sm">
        {message}
      </p>
    </div>
  );
}
