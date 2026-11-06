import PageHeader from "@/components/PageHeader";
import Alerts from "@/features/alerts/Alerts";

export default function AlertsPage() {
  return (
    <>
      <PageHeader
        title="Alertes"
        intro="Les incidents et les seuils dépassés à surveiller, mis à jour en direct."
      />
      <Alerts />
    </>
  );
}
