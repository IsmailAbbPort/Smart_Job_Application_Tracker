import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./theme.css";

// Apply the saved colour scheme before first paint to avoid a flash.
// Light is the default; only "dark" is a valid alternate.
document.documentElement.dataset.theme =
  localStorage.getItem("sjt.colorScheme") === "dark" ? "dark" : "light";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
