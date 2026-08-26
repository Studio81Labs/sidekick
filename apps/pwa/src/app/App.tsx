import { BrowserRouter } from "react-router-dom";

import { AppProviders } from "./providers/AppProviders";
import { PwaRuntime } from "./pwa/PwaRuntime";
import { AppRoutes } from "./routes";

export default function App() {
  return (
    <AppProviders>
      <PwaRuntime />
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AppProviders>
  );
}
