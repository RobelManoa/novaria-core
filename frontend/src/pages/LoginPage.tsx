import { useEffect } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import Container from "@/components/Container";
import PageHeader from "@/components/PageHeader";
import { useAuth } from "@/features/auth/AuthContext";
import LoginForm from "@/features/auth/LoginForm";
import { redirectTarget } from "@/features/auth/redirect";
import styles from "./LoginPage.module.css";

export default function LoginPage() {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const { state } = useLocation();

  useEffect(() => {
    document.title = "Connexion · Novaria Core";
  }, []);

  // Déjà connecté : la page de connexion n'a plus d'objet.
  if (isAuthenticated) return <Navigate to={redirectTarget(state)} replace />;

  return (
    <main className={styles.page}>
      <Container>
        <div className={styles.card}>
          <PageHeader
            title="Connexion"
            intro="Connectez-vous pour accéder au tableau de bord Novaria Core."
          />
          <LoginForm onSuccess={() => navigate(redirectTarget(state), { replace: true })} />
        </div>
      </Container>
    </main>
  );
}
