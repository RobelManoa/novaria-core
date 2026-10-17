import { Link } from "react-router";
import PageHeader from "@/components/PageHeader";
import styles from "./NotFoundPage.module.css";

export default function NotFoundPage() {
  return (
    <>
      <PageHeader
        title="Page introuvable"
        intro="La page demandée n'existe pas ou a été déplacée."
      />
      <Link to="/" className={styles.back}>
        Retour au tableau de bord
      </Link>
    </>
  );
}
