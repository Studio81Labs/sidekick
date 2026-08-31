import ReactDOM from "react-dom/client";

import PlayerApp from "./PlayerApp";
import "./styles.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);
root.render(<PlayerApp />);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js", {
      scope: "/",
      updateViaCache: "none",
    });
  });
}
