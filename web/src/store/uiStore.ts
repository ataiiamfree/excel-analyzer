import { create } from "zustand";

interface UiState {
  artifactPanelOpen: boolean;
  activeArtifactId?: string;
  setArtifactPanelOpen: (open: boolean) => void;
  setActiveArtifactId: (id?: string) => void;
}

export const useUiStore = create<UiState>((set) => ({
  artifactPanelOpen: true,
  setArtifactPanelOpen: (open) => set({ artifactPanelOpen: open }),
  setActiveArtifactId: (id) => set({ activeArtifactId: id, artifactPanelOpen: true })
}));
