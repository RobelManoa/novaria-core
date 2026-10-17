import ComingSoon from "@/components/ComingSoon";
import PageHeader from "@/components/PageHeader";

export default function ForecastsPage() {
  return (
    <>
      <PageHeader
        title="Prévisions"
        intro="Les prévisions de mobilité pour les prochaines heures."
      />
      <ComingSoon />
    </>
  );
}
