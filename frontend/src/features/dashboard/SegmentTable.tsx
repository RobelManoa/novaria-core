import type { Indicator } from "@/services/traitement";
import { formatDateTime, formatNumber } from "./format";
import { STATE_LABELS } from "./labels";
import styles from "./SegmentTable.module.css";

/** Dernière fenêtre de chaque tronçon : les valeurs brutes de l'API, sans calcul. */
export default function SegmentTable({ items }: Readonly<{ items: readonly Indicator[] }>) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <caption className={styles.caption}>Dernière fenêtre de chaque tronçon</caption>
        <thead>
          <tr>
            <th scope="col">Tronçon</th>
            <th scope="col">Carrefour</th>
            <th scope="col">État</th>
            <th scope="col">Vitesse (km/h)</th>
            <th scope="col">Débit (véh/min)</th>
            <th scope="col">Véhicules</th>
            <th scope="col">Fenêtre (UTC)</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.road_segment_id}>
              <th scope="row">{item.road_segment_id}</th>
              <td>{item.intersection_id}</td>
              <td>{STATE_LABELS[item.congestion_state]}</td>
              <td className={styles.number}>{formatNumber(item.average_speed_kmh, 1)}</td>
              <td className={styles.number}>{formatNumber(item.flow_veh_per_min, 1)}</td>
              <td className={styles.number}>{formatNumber(item.vehicle_count, 0)}</td>
              <td>{formatDateTime(Date.parse(item.window_start))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
