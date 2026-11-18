// The same error card the server shows (404, 403, 500 ...), for problems inside the web app:
// a screen that crashes, or a back-office page that does not exist or is not open to this role.
import { Component, ReactNode } from "react";

export function ErrorCard({ code, title, message, reference, home = "#/", inline = false }: {
  code: number | string; title: string; message: string; reference?: string; home?: string; inline?: boolean;
}) {
  return (
    <div className={inline ? "error-wrap inline" : "error-wrap"}>
      <main className="error-card" role="alert">
        <p className={`error-code ${Number(code) >= 500 ? "bad" : ""}`}>{code}</p>
        <h1>{title}</h1>
        <p>{message}</p>
        {reference && <div className="error-ref">Reference: {reference}</div>}
        <div className="actions" style={{ justifyContent: "center" }}>
          <button onClick={() => (history.length > 1 ? history.back() : location.assign(home))}>Go back</button>
          <button className="primary" onClick={() => { location.hash = home.replace(/^#/, ""); location.reload(); }}>
            {home.startsWith("#/office") ? "Back office home" : "Go to the POS"}
          </button>
        </div>
      </main>
    </div>
  );
}

/** Catches a crash anywhere below it and shows the error card instead of a blank screen. The technical
 *  details go to the browser console with the same reference, never onto the screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { ref: string | null }> {
  state = { ref: null as string | null };

  static getDerivedStateFromError() {
    return { ref: "UI-" + Math.random().toString(16).slice(2, 8).toUpperCase() };
  }

  componentDidCatch(error: unknown, info: { componentStack?: string | null }) {
    console.error(`Screen error ${this.state.ref}`, error, info.componentStack);
  }

  render() {
    if (this.state.ref) {
      return <ErrorCard code={500} title="Something went wrong"
        message="This screen hit a problem. Your sales and data are safe - reload to carry on."
        reference={this.state.ref} />;
    }
    return this.props.children;
  }
}
