import PageHeader from "@/components/PageHeader";
import Dashboard from "@/features/dashboard/Dashboard";

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="Tableau de bord" intro="Vue d'ensemble des indicateurs de la ville." />
      <Dashboard />
    </>
  );
}
