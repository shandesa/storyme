/**
 * App.js — root component.
 *
 * Delegates all routing to AppRoutes.
 * Previously this file contained the monolithic Home component AND
 * a BrowserRouter — both have been extracted to:
 *   - src/pages/HomePage.jsx   (Home UI)
 *   - src/AppRoutes.jsx        (router + all routes)
 */

import AppRoutes from "@/AppRoutes";

export default function App() {
  return <AppRoutes />;
}
