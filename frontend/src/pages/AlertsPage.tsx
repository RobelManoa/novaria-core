import ComingSoon from "@/components/ComingSoon";
import PageHeader from "@/components/PageHeader";

export default function AlertsPage() {
  return (
    <>
      <PageHeader title="Alertes" intro="Les incidents et les seuils dépassés à surveiller." />
      <ComingSoon />
    </>
  );
}
