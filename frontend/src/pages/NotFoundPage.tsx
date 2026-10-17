import { Link } from "react-router";
import PageHeader from "@/components/PageHeader";

export default function NotFoundPage() {
  return (
    <>
      <PageHeader
        title="Page introuvable"
        intro="La page demandée n'existe pas ou a été déplacée."
      />
      <Link to="/">Retour au tableau de bord</Link>
    </>
  );
}
