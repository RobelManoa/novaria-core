import ComingSoon from "@/components/ComingSoon";
import PageHeader from "@/components/PageHeader";

export default function TrafficLightsPage() {
  return (
    <>
      <PageHeader
        title="Feux de circulation"
        intro="L'état des carrefours et de leur signalisation."
      />
      <ComingSoon />
    </>
  );
}
