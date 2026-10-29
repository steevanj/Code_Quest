import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import React from "react";
import ReactDOM from "react-dom/client";
import "@xyflow/react/dist/style.css";
import App from "./App";
import "./styles.css";

// Bundle Monaco locally instead of loading it from a CDN, so the IDE works offline.
self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

monaco.editor.defineTheme("forge", {
  base: "vs-dark",
  inherit: true,
  rules: [
    { token: "keyword", foreground: "f59e0b" },
    { token: "string", foreground: "86efac" },
    { token: "comment", foreground: "64748b", fontStyle: "italic" },
    { token: "number", foreground: "fda4af" },
    { token: "type", foreground: "7dd3fc" },
  ],
  colors: {
    "editor.background": "#0d1117",
    "editor.lineHighlightBackground": "#161b2299",
    "editorLineNumber.foreground": "#3b4452",
    "editorLineNumber.activeForeground": "#9aa4b2",
    "editorGutter.background": "#0d1117",
    "editor.selectionBackground": "#f59e0b33",
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
