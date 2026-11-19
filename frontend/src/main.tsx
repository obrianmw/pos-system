import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "@fontsource-variable/inter";
import "./styles.css";
import "./theme"; // applies the saved light/dark choice before the first paint
import { Toaster } from "./backoffice/ui";
import { ErrorBoundary } from "./ErrorCard";
import { DialogHost } from "./Dialog";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
    <Toaster />
    <DialogHost />
  </React.StrictMode>,
);
