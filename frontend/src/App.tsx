import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import ExperimentsPage from './pages/ExperimentsPage';
import ExperimentPage from './pages/ExperimentPage';
import PlaybookPage from './pages/PlaybookPage';
import MemoryPage from './pages/MemoryPage';
import { ErrorBoundary } from './components/ErrorBoundary';
import { useAuth } from './context/AuthContext';

function App() {
  const { isAuthenticated } = useAuth();

  return (
    <BrowserRouter>
      <ErrorBoundary fallbackTitle="The app">
        <Routes>
          <Route path="/login" element={!isAuthenticated ? <LoginPage /> : <Navigate to="/" replace />} />
          <Route path="/" element={isAuthenticated ? <Layout /> : <Navigate to="/login" replace />}>
            <Route index element={<ExperimentsPage />} />
            <Route path="experiments/:experimentId" element={<ExperimentPage />} />
            <Route path="memory" element={<MemoryPage />} />
            {/* LLM agents' playbook: kept for LLM experiments, not in the navigation. */}
            <Route path="playbook" element={<PlaybookPage />} />
          </Route>
          <Route path="*" element={<Navigate to={isAuthenticated ? '/' : '/login'} replace />} />
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  );
}

export default App;
