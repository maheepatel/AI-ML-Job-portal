import { Component, StrictMode, useEffect, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { Footer, Nav } from "./components/ui";
import Apply from "./pages/Apply";
import Funded from "./pages/Funded";
import HiringPosts from "./pages/HiringPosts";
import Latest from "./pages/Latest";
import ForMe from "./pages/ForMe";
import Home from "./pages/Home";
import JobPage from "./pages/JobPage";
import Jobs from "./pages/Jobs";
import Status from "./pages/Status";
import { Privacy, Terms } from "./pages/Legal";
import "./styles.css";

const DEFAULT_TITLE = document.title;

function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
    document.title = DEFAULT_TITLE; // job pages set their own once loaded
  }, [pathname]);
  return null;
}

class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.error("render error", error);
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="container" style={{ padding: "96px 16px", textAlign: "center" }}>
        <h1 style={{ fontSize: 48 }}>Something broke</h1>
        <p className="muted">This page hit an error. Reloading usually fixes it.</p>
        <button type="button" className="btn btn-ink" onClick={() => window.location.assign("/")}>Back to home</button>
      </div>
    );
  }
}

function NotFound() {
  return (
    <div className="container" style={{ padding: "96px 16px", textAlign: "center" }}>
      <h1 style={{ fontSize: 56 }}>404</h1>
      <p className="muted">This page doesn't exist — the job may have moved.</p>
      <Link to="/jobs" className="btn btn-ink">Browse jobs</Link>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ScrollTop />
      <Nav />
      <main>
        <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<JobPage />} />
          <Route path="/closed" element={<Jobs status="closed" />} />
          <Route path="/for-me" element={<ForMe />} />
          <Route path="/status" element={<Status />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/terms" element={<Terms />} />
          <Route path="/apply" element={<Apply />} />
          <Route path="/latest" element={<Latest />} />
          <Route path="/hiring-posts" element={<HiringPosts />} />
          <Route path="/funded" element={<Funded />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        </ErrorBoundary>
      </main>
      <Footer />
    </BrowserRouter>
  </StrictMode>,
);
