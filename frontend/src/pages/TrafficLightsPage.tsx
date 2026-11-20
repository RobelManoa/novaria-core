import PageHeader from "@/components/PageHeader";
import Signals from "@/features/signals/Signals";

export default function TrafficLightsPage() {
  return (
    <>
      <PageHeader
        title="Feux de circulation"
        intro="L'état des carrefours, la commande manuelle et son journal."
      />
      <Signals />
    </>
  );
}
