import { create } from "zustand";

interface UiState {
  artifactPanelOpen: boolean;
  mobileSidebarOpen: boolean;
  activeArtifactId?: string;
  setArtifactPanelOpen: (open: boolean) => void;
  setMobileSidebarOpen: (open: boolean) => void;
  setActiveArtifactId: (id?: string) => void;
}

export const useUiStore = create<UiState>((set) => ({
  artifactPanelOpen: true,
  mobileSidebarOpen: false,
  setArtifactPanelOpen: (open) => set({ artifactPanelOpen: open }),
  setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
  setActiveArtifactId: (id) => set({ activeArtifactId: id, artifactPanelOpen: true })
}));
