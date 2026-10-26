import { useCallback, useEffect, useRef } from "react";
import { Link, Outlet, useLocation, useMatches } from "react-router";
import IconButton from "@/components/IconButton";
import SkipLink from "@/components/SkipLink";
import ApiStatus from "@/features/api-status/ApiStatus";
import MainNav from "@/features/navigation/MainNav";
import ThemeSelector from "@/features/theme/ThemeSelector";
import { useDisclosure } from "@/hooks/useDisclosure";
import { useEscapeKey } from "@/hooks/useEscapeKey";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useScrollLock } from "@/hooks/useScrollLock";
import { DESKTOP_QUERY } from "@/styles/breakpoints";
import { isRouteHandle } from "@/types/route";
import { CloseIcon, MenuIcon } from "./icons";
import styles from "./AppShell.module.css";

const MAIN_ID = "contenu";
const NAV_ID = "navigation-principale";
const APP_NAME = "Novaria Core";

/**
 * Mise en page commune : lien d'évitement, en-tête, navigation, contenu et pied de page.
 * Sur ordinateur la navigation est une barre latérale ; en dessous, c'est un tiroir.
 */
export default function AppShell() {
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const drawer = useDisclosure();
  const { close } = drawer;
  const { pathname } = useLocation();
  const matches = useMatches();

  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const restoreFocus = useRef(false);
  const previousPath = useRef(pathname);

  const drawerOpen = drawer.isOpen && !isDesktop;
  const navHidden = !isDesktop && !drawerOpen;

  // Fermeture voulue par l'utilisateur (Échap, voile, bouton) : le focus revient sur le bouton de menu.
  const closeAndRestoreFocus = useCallback(() => {
    restoreFocus.current = true;
    close();
  }, [close]);

  useEscapeKey(closeAndRestoreFocus, drawerOpen);
  useFocusTrap(navRef, drawerOpen);
  useScrollLock(drawerOpen);

  // Le tiroir se ferme au changement de page et quand la fenêtre repasse en largeur ordinateur.
  useEffect(() => {
    close();
  }, [pathname, close]);

  useEffect(() => {
    if (isDesktop) close();
  }, [isDesktop, close]);

  useEffect(() => {
    if (drawerOpen) {
      navRef.current?.querySelector<HTMLElement>("a")?.focus();
    } else if (restoreFocus.current) {
      restoreFocus.current = false;
      menuButtonRef.current?.focus();
    }
  }, [drawerOpen]);

  // Titre du document et focus sur le h1 à chaque changement de page (pas au premier chargement).
  const handle = matches.at(-1)?.handle;
  const pageTitle = isRouteHandle(handle) ? handle.title : null;
  useEffect(() => {
    document.title = pageTitle ? `${pageTitle} · ${APP_NAME}` : APP_NAME;
  }, [pageTitle]);

  useEffect(() => {
    if (previousPath.current === pathname) return;
    previousPath.current = pathname;
    mainRef.current?.querySelector("h1")?.focus();
  }, [pathname]);

  return (
    <div className={styles.shell}>
      <SkipLink targetId={MAIN_ID}>Aller au contenu</SkipLink>

      <header className={styles.header} inert={drawerOpen}>
        <IconButton
          ref={menuButtonRef}
          className={styles.menuButton}
          label={drawerOpen ? "Fermer le menu" : "Ouvrir le menu"}
          aria-expanded={drawerOpen}
          aria-controls={NAV_ID}
          onClick={drawerOpen ? closeAndRestoreFocus : drawer.open}
        >
          <MenuIcon />
        </IconButton>
        <Link to="/" className={styles.brand}>
          {APP_NAME}
        </Link>
        <div className={styles.tools}>
          <ApiStatus />
          <ThemeSelector />
        </div>
      </header>

      <nav
        id={NAV_ID}
        ref={navRef}
        aria-label="Navigation principale"
        className={drawerOpen ? `${styles.nav} ${styles.navOpen}` : styles.nav}
        inert={navHidden}
      >
        <div className={styles.navHeader}>
          <IconButton label="Fermer le menu" onClick={closeAndRestoreFocus}>
            <CloseIcon />
          </IconButton>
        </div>
        <MainNav onNavigate={close} />
      </nav>

      {drawerOpen && (
        <div
          className={styles.overlay}
          data-testid="voile"
          aria-hidden="true"
          onClick={closeAndRestoreFocus}
        />
      )}

      <main id={MAIN_ID} ref={mainRef} tabIndex={-1} className={styles.main} inert={drawerOpen}>
        <div className={styles.content}>
          <Outlet />
        </div>
      </main>

      <footer className={styles.footer} inert={drawerOpen}>
        {APP_NAME} · socle de données et d'intelligence artificielle d'UrbanHub
      </footer>
    </div>
  );
}
