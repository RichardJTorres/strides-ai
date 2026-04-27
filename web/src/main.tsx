import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { UnitsProvider } from "./UnitsContext";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <UnitsProvider>
      <App />
    </UnitsProvider>
  </StrictMode>
);
