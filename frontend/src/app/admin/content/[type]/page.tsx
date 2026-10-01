import { EntityList } from "@/features/admin/content/entity-list";

export default async function ContentTypePage(props: PageProps<"/admin/content/[type]">) {
  const { type } = await props.params;
  return (
    <div className="space-y-3">
      <h1 className="font-mono text-xl font-bold">{type}</h1>
      <EntityList type={type} />
    </div>
  );
}
