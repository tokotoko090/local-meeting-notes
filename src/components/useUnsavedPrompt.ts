import { useEffect } from "react";

export function useUnsavedPrompt(dirty: boolean, saving: boolean) {
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.promptDirty = String(dirty);
    root.dataset.promptSaving = String(saving);
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty || saving) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      delete root.dataset.promptDirty;
      delete root.dataset.promptSaving;
      window.removeEventListener("beforeunload", warn);
    };
  }, [dirty, saving]);
}
