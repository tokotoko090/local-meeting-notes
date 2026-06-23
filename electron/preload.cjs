const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("meetingNotes", {
  listDevices: () => ipcRenderer.invoke("devices:list"),
  startRecording: (options) => ipcRenderer.invoke("recording:start", options),
  stopRecording: () => ipcRenderer.invoke("recording:stop"),
  transcribeExisting: (options) => ipcRenderer.invoke("transcribe:existing", options),
  pickOutputFolder: () => ipcRenderer.invoke("output:pick-directory"),
  openOutputFolder: (outputDir) => ipcRenderer.invoke("output:open", outputDir),
  copyPrompt: (outputDir) => ipcRenderer.invoke("prompt:copy", outputDir),
  onBackendEvent: (callback) => {
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("backend:event", listener);
    return () => ipcRenderer.removeListener("backend:event", listener);
  }
});
