import PageHeader from "@/components/PageHeader";
import Forecasts from "@/features/forecasts/Forecasts";

export default function ForecastsPage() {
  return (
    <>
      <PageHeader
        title="Prévisions"
        intro="Le ratio de vitesse prévu pour les prochaines minutes, face à ce qui a été observé."
      />
      <Forecasts />
    </>
  );
}
