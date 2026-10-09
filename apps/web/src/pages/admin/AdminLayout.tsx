import { Link, NavLink, Outlet } from "react-router";

import { useAuth } from "../../api/hooks";
import { PageHead } from "../../components/ui";
import "./admin.css";

/**
 * Shell for the admin pages (R2). Only users with `is_admin` (ADMIN_EMAILS) see the area; the API
 * also answers 404 to everyone else, so this check is for the screen only.
 */
export function AdminLayout() {
  const auth = useAuth();
  if (!auth.data?.user?.is_admin) {
    return (
      <PageHead title="Page not found">
        <p>
          This page does not exist. <Link to="/">Go to the dashboard</Link>.
        </p>
      </PageHead>
    );
  }
  return (
    <>
      <nav className="admin-nav" aria-label="Admin">
        <ul>
          <li>
            <NavLink to="/admin/interviews" end={false}>
              Interviews
            </NavLink>
          </li>
          <li>
            <NavLink to="/admin/users">Users</NavLink>
          </li>
          <li>
            <NavLink to="/admin/audit">Audit log</NavLink>
          </li>
        </ul>
      </nav>
      <Outlet />
    </>
  );
}
