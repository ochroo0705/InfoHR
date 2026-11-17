import { useEffect } from "react";
import { Route, Routes } from "react-router";
import LoginPage from "./routes/LoginPage";

export default function App() {
  useEffect(() => {
    document.documentElement.lang = "mn";
  }, []);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<p>Нэвтэрсэн</p>} />
    </Routes>
  );
}
