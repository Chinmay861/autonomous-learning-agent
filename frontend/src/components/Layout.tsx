import React from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const Layout = () => {
  const { user, logout } = useAuth();
  const location = useLocation();

  const navItems = [
    { name: 'Dashboard', path: '/' },
    { name: 'Memory Explorer', path: '/memory' },
    { name: 'Settings', path: '/settings' }
  ];

  const isActive = (path: string) =>
    path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>

      <aside className="flex shrink-0 flex-col border-b border-slate-700 bg-slate-800 lg:sticky lg:top-0 lg:h-screen lg:w-64 lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between gap-3 px-4 py-3 lg:border-b lg:border-slate-700 lg:py-5">
          <Link to="/" className="min-w-0 truncate text-lg font-semibold text-emerald-300">
            Autonomous Agent
          </Link>
          <button type="button" onClick={logout} className="btn-ghost shrink-0 px-2 py-1 text-xs lg:hidden">
            Log out
          </button>
        </div>

        <nav
          aria-label="Primary"
          className="flex gap-1 overflow-x-auto px-3 pb-2 lg:flex-1 lg:flex-col lg:overflow-visible lg:p-4"
        >
          {navItems.map((item) => {
            const active = isActive(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                aria-current={active ? 'page' : undefined}
                className={`whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors lg:px-4 ${
                  active
                    ? 'bg-slate-700 text-emerald-300'
                    : 'text-slate-300 hover:bg-slate-700/50 hover:text-white'
                }`}
              >
                {item.name}
              </Link>
            );
          })}
        </nav>

        <div className="hidden border-t border-slate-700 p-4 lg:block">
          {user?.email && (
            <div className="mb-3 truncate text-xs text-slate-400" title={user.email}>
              {user.email}
            </div>
          )}
          <button type="button" onClick={logout} className="btn-ghost w-full justify-start px-2">
            Log out
          </button>
        </div>
      </aside>

      <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 focus:outline-none">
        <div className="p-4 sm:p-6 lg:p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
};

export default Layout;
