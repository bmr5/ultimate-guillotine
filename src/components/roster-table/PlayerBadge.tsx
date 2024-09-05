// import { CURRENT_WEEK } from "@/app/constants";
// import {
//   getProjectedPoints,
//   usePlayerProjections,
// } from "@/queries/usePlayerProjections";

import { Badge } from "../ui/badge";
import { getPositionColor } from "./getPositionColor";
import { Player } from "./RosterTable";

type Props = {
  player: Player;
};

export const PlayerBadge = ({ player }: Props) => {
  //   const {
  //     data: projections,
  //     isLoading,
  //     error,
  //   } = usePlayerProjections(player.id);

  //   const projectedPoints = isLoading
  //     ? "Loading..."
  //     : projections
  //     ? getProjectedPoints(projections, CURRENT_WEEK).toFixed(2)
  //     : "N/A";

  return (
    <Badge
      key={player.id}
      className={`mb-1 mr-1 ${getPositionColor(player.position)}`}
    >
      {/* {player.name} ({player.position}) ({player.team}) - {projectedPoints} */}
      {player.name} ({player.position}) ({player.team})
    </Badge>
  );
};
