import PageHeader from "@/components/PageHeader";
import Reports from "@/features/reports/Reports";

export default function ReportsPage() {
  return (
    <>
      <PageHeader
        title="Rapports"
        intro="Les rapports périodiques de supervision générés par le robot, à télécharger."
      />
      <Reports />
    </>
  );
}
