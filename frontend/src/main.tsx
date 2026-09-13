import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./theme.css";

// Apply the saved colour scheme before first paint to avoid a flash.
// Default to dark for new visitors; only "light" is a valid alternate.
document.documentElement.dataset.theme =
  localStorage.getItem("sjt.theme") === "light" ? "light" : "dark";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
