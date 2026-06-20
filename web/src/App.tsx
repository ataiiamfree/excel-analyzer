import { Navigate, Route, Routes } from "react-router-dom";

import ConversationPage from "./pages/ConversationPage";
import HomePage from "./pages/HomePage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/c/:conversationId" element={<ConversationPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
