import { SiGithub, SiJira, SiTrello } from "@icons-pack/react-simple-icons";
import { FaSlack } from "react-icons/fa";

export type IntegrationId = "trello" | "github" | "jira" | "slack";

const brandIcons = {
  trello: { Icon: SiTrello, color: "#0052CC" },
  github: { Icon: SiGithub, color: "#181717" },
  jira: { Icon: SiJira, color: "#1868DB" },
};

export function IntegrationLogo({
  app,
  className = "h-5 w-5",
}: {
  app: IntegrationId;
  className?: string;
}) {
  if (app === "slack") {
    return <FaSlack aria-label="Slack" className={className} color="#4A154B" />;
  }

  const { Icon, color } = brandIcons[app];
  return <Icon aria-label={app} className={className} color={color} />;
}
