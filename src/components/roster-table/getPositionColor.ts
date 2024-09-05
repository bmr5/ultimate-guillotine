export const getPositionColor = (position: string) => {
  switch (position) {
    case "QB":
      return "bg-red-800 text-white";
    case "RB":
      return "bg-blue-800 text-white";
    case "WR":
      return "bg-green-800 text-white";
    case "TE":
      return "bg-yellow-800 text-black";
    case "K":
      return "bg-purple-800 text-white";
    case "DEF":
      return "bg-gray-800 text-white";
    default:
      return "bg-gray-300 text-black";
  }
};
