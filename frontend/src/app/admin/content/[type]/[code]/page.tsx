import { EntityEditor } from "@/features/admin/content/entity-editor";

export default async function ContentEntityPage(props: PageProps<"/admin/content/[type]/[code]">) {
  const { type, code } = await props.params;
  return <EntityEditor type={type} code={decodeURIComponent(code)} />;
}
