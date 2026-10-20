import ComingSoon from "@/components/ComingSoon";
import PageHeader from "@/components/PageHeader";

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="Tableau de bord" intro="Vue d'ensemble des indicateurs de la ville." />
      <ComingSoon />
    </>
  );
}
