import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs';
import { CatalogPreview } from './catalog-workspace';
import { ConfirmButton, PaginatedRecords } from './management-widgets';
import { FormSelect } from './form-select';
import { catalogCategoryLabel } from '../lib/catalog';
import { formatCell, playerHref, relative, type Row } from '../lib/panel';

type Api = (path: string, body?: Row) => Promise<any>;
type Mutate = (path: string, body: Row) => Promise<boolean>;
const genderLabel = (value: unknown) =>
  value === 'MALE' ? 'Male' : value === 'FEMALE' ? 'Female' : String(value || '—');
const itemName = (row: Row) =>
  String(row.label || row.display_name || row.category_label || 'Item');

function ItemTile({ row, action }: { row: Row; action?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-md border p-2">
      <div className="w-10 shrink-0">
        <CatalogPreview row={row} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={itemName(row)}>
          {itemName(row)}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {String(
            row.slot ? catalogCategoryLabel({ category: row.slot }) : catalogCategoryLabel(row),
          )}
          {row.owned === false && ' · not owned'}
          {row.starter === true && ' · starter'}
        </p>
      </div>
      {action}
    </div>
  );
}

function Outfit({ data }: { data: Row }) {
  const outfit = data.outfit as Row | null;
  const equipped = (data.equipped || {}) as Row;
  const items = (outfit?.items as Row[]) || [];
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="secondary">{genderLabel(outfit?.gender || data.gender)}</Badge>
        {outfit ? (
          <span className="text-muted-foreground">
            Outfit <strong className="text-foreground">{String(outfit.preset_name)}</strong> · saved{' '}
            {relative(outfit.updated_at)}
          </span>
        ) : (
          <span className="text-muted-foreground">No saved outfit yet.</span>
        )}
      </div>
      {items.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map((row, index) => (
            <ItemTile key={String(row.item_id) + index} row={row} />
          ))}
        </div>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        {(['companion', 'locomotion'] as const).map((kind) => {
          const row = equipped[kind] as Row | null;
          return row ? (
            <ItemTile key={kind} row={row} />
          ) : (
            <p
              key={kind}
              className="rounded-md border border-dashed p-2 text-xs text-muted-foreground"
            >
              No {kind} equipped
            </p>
          );
        })}
      </div>
    </div>
  );
}

function Presets({ base, api, mutate, saving, revision, canEdit }: Section) {
  const [renaming, setRenaming] = useState<Row | null>(null),
    [name, setName] = useState('');
  return (
    <PaginatedRecords
      title="Saved outfits"
      path={base + '/presets'}
      revision={revision}
      load={api}
      renderItems={(items) => (
        <ul className="divide-y rounded-md border">
          {items.map((row) => (
            <li
              key={String(row.preset_name) + String(row.gender)}
              className="grid gap-2 p-2 sm:grid-cols-[1fr_auto]"
            >
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 font-medium">
                  {String(row.preset_name)}
                  <Badge variant="outline">{genderLabel(row.gender)}</Badge>
                  {row.selected === true && <Badge>Selected</Badge>}
                  {row.active === true && <Badge variant="secondary">Wearing now</Badge>}
                </p>
                <p className="text-xs text-muted-foreground">
                  {String(row.item_count)} items
                  {Number(row.unowned_item_count) > 0 && ` · ${row.unowned_item_count} not owned`} ·
                  saved {relative(row.updated_at)}
                </p>
                {Array.isArray(row.preview_items) && (
                  <div className="mt-1 flex gap-1">
                    {(row.preview_items as Row[]).map((item, index) => (
                      <div key={index} className="w-8" title={itemName(item)}>
                        <CatalogPreview row={item} />
                      </div>
                    ))}
                  </div>
                )}
                {renaming === row && (
                  <form
                    className="mt-2 flex gap-2"
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (
                        await mutate(base + '/presets/rename', {
                          name: row.preset_name,
                          gender: row.gender,
                          new_name: name.trim(),
                        })
                      )
                        setRenaming(null);
                    }}
                  >
                    <Input
                      value={name}
                      maxLength={64}
                      onChange={(e) => setName(e.target.value)}
                      className="min-h-8"
                      autoFocus
                    />
                    <Button size="sm" disabled={saving || !name.trim()}>
                      Save
                    </Button>
                    <Button
                      size="sm"
                      type="button"
                      variant="ghost"
                      onClick={() => setRenaming(null)}
                    >
                      Cancel
                    </Button>
                  </form>
                )}
              </div>
              {canEdit && (
                <div className="flex flex-wrap items-start justify-end gap-1">
                  {row.selected !== true && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={saving}
                      onClick={() =>
                        mutate(base + '/presets/select', {
                          name: row.preset_name,
                          gender: row.gender,
                          activate_gender: true,
                        })
                      }
                    >
                      Wear
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setRenaming(row);
                      setName(String(row.preset_name));
                    }}
                  >
                    Rename
                  </Button>
                  <ConfirmButton
                    label="Delete"
                    variant="ghost"
                    disabled={saving}
                    onConfirm={() =>
                      mutate(base + '/presets/delete', {
                        name: row.preset_name,
                        gender: row.gender,
                      })
                    }
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    />
  );
}

function Preferences({ base, api, mutate, saving, revision, canEdit }: Section) {
  return (
    <PaginatedRecords
      title="Game settings"
      path={base + '/preferences'}
      revision={revision}
      load={api}
      renderItems={(items) => (
        <ul className="divide-y rounded-md border">
          {items.map((row) => (
            <PreferenceRow
              key={String(row.key)}
              row={row}
              base={base}
              mutate={mutate}
              saving={saving}
              canEdit={canEdit}
            />
          ))}
        </ul>
      )}
    />
  );
}

function PreferenceRow({
  row,
  base,
  mutate,
  saving,
  canEdit,
}: {
  row: Row;
  base: string;
  mutate: Mutate;
  saving: boolean;
  canEdit: boolean;
}) {
  const [value, setValue] = useState(String(row.value ?? ''));
  useEffect(() => setValue(String(row.value ?? '')), [row.value]);
  const editable = canEdit && row.editable === true;
  const save = (next: unknown) => mutate(base + '/preferences/set', { key: row.key, value: next });
  return (
    <li className="grid items-center gap-2 p-2 sm:grid-cols-[1fr_14rem]">
      <div className="min-w-0">
        <p className="text-sm font-medium">{String(row.label || row.key)}</p>
        <p className="text-xs text-muted-foreground">
          {String(row.group || '')}
          {row.stored === false && ' · default'}
        </p>
      </div>
      {!editable ? (
        <span className="text-sm">{formatCell('value', row.value)}</span>
      ) : row.type === 'flag' ? (
        <div className="flex gap-1">
          {[true, false].map((option) => (
            <Button
              key={String(option)}
              size="sm"
              variant={row.value === option || row.value === Number(option) ? 'default' : 'outline'}
              disabled={saving}
              onClick={() => save(option)}
            >
              {option ? 'On' : 'Off'}
            </Button>
          ))}
        </div>
      ) : (
        <form
          className="flex gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            void save(row.type === 'number' ? Number(value) : value);
          }}
        >
          <Input
            value={value}
            type={row.type === 'number' ? 'number' : 'text'}
            min={typeof row.minimum === 'number' ? row.minimum : undefined}
            max={typeof row.maximum === 'number' ? row.maximum : undefined}
            onChange={(e) => setValue(e.target.value)}
            className="min-h-8"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={saving || value === String(row.value ?? '')}
          >
            Save
          </Button>
        </form>
      )}
    </li>
  );
}

function Social({ base, api, mutate, saving, revision, canEdit }: Section) {
  const flags = (row: Row) =>
    [
      row.is_friend && 'Friend',
      row.mutual_friend && 'Mutual',
      row.is_favorite && 'Favorite',
      row.is_blocked && 'Blocked',
      row.is_silenced && 'Silenced',
      row.blocked_by_them && 'Blocked them back',
    ].filter(Boolean) as string[];
  return (
    <PaginatedRecords
      title="Friends and blocks"
      path={base + '/social'}
      revision={revision}
      load={api}
      emptyText="No friends or blocks yet."
      renderItems={(items) => (
        <ul className="divide-y rounded-md border">
          {items.map((row, index) => (
            <li key={String(row.target) + index} className="flex flex-wrap items-center gap-2 p-2">
              <span className="min-w-0 flex-1 truncate font-medium">
                {typeof row.target_account_id === 'string' ? (
                  <a href={playerHref(row.target_account_id)} className="hover:underline">
                    {String(row.target)}
                  </a>
                ) : (
                  String(row.target)
                )}
              </span>
              {flags(row).map((flag) => (
                <Badge key={flag} variant={flag === 'Blocked' ? 'destructive' : 'secondary'}>
                  {flag}
                </Badge>
              ))}
              {canEdit &&
                (['friend', 'favorite', 'block', 'silenced'] as const)
                  .filter(
                    (kind) =>
                      row[
                        {
                          friend: 'is_friend',
                          favorite: 'is_favorite',
                          block: 'is_blocked',
                          silenced: 'is_silenced',
                        }[kind]
                      ],
                  )
                  .map((kind) => (
                    <ConfirmButton
                      key={kind}
                      variant="ghost"
                      disabled={saving}
                      label={
                        {
                          friend: 'Unfriend',
                          favorite: 'Unfavorite',
                          block: 'Unblock',
                          silenced: 'Unsilence',
                        }[kind]
                      }
                      onConfirm={() =>
                        mutate(base + '/social/remove', {
                          kind,
                          target: row.target,
                          platform: row.target_platform,
                        })
                      }
                    />
                  ))}
            </li>
          ))}
        </ul>
      )}
    />
  );
}

function GrantApartment({ base, api, mutate, saving, revision }: Section) {
  const [options, setOptions] = useState<Row[]>([]),
    [choice, setChoice] = useState('');
  useEffect(() => {
    let current = true;
    api(base + '/housing-options')
      .then((value) => current && setOptions((value?.items as Row[]) || []))
      .catch(() => current && setOptions([]));
    return () => {
      current = false;
    };
  }, [api, base, revision]);
  const available = options.filter((row) => row.owned !== true);
  if (!available.length) return null;
  return (
    <form
      className="flex items-center gap-1"
      onSubmit={async (event) => {
        event.preventDefault();
        if (choice && (await mutate(base + '/housing/grant', { space_key: choice }))) setChoice('');
      }}
    >
      <FormSelect
        id="grant-apartment"
        value={choice}
        onValueChange={setChoice}
        className="w-44 text-xs"
        options={available.map((row) => ({
          value: String(row.space_key),
          label: String(row.space_label || row.space_key),
        }))}
      />
      <Button size="sm" disabled={saving || !choice}>
        Give
      </Button>
    </form>
  );
}

function Housing(props: Section) {
  const { base, api, mutate, saving, revision, canEdit } = props;
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="grid gap-3">
      <PaginatedRecords
        title="Apartments"
        path={base + '/housing'}
        revision={revision}
        load={api}
        emptyText="No apartments yet."
        headerAction={canEdit ? <GrantApartment {...props} /> : undefined}
        renderItems={(items) => (
          <ul className="divide-y rounded-md border">
            {items.map((row) => (
              <li key={String(row.instance_id)} className="flex flex-wrap items-center gap-2 p-2">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {String(row.space_label || row.space_key || 'Apartment')}
                    {row.default === true && <Badge variant="secondary">Default</Badge>}
                    {row.default !== true && row.starter === true && (
                      <Badge variant="outline">Starter</Badge>
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {String(row.placed_count ?? 0)} furniture placed ·{' '}
                    {String(row.placement_used ?? 0)}/{String(row.placement_max ?? '—')} slots
                    {row.layout_updated_at
                      ? ' · saved ' + relative(row.layout_updated_at)
                      : ' · never saved'}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setOpen(open === row.instance_id ? null : String(row.instance_id))}
                >
                  {open === row.instance_id ? 'Hide' : 'Furniture'}
                </Button>
                {canEdit && row.layout_saved === true && (
                  <ConfirmButton
                    label="Reset layout"
                    variant="ghost"
                    disabled={saving || row.save_in_progress === true}
                    onConfirm={() =>
                      mutate(base + '/housing/reset-layout', { instance_id: row.instance_id })
                    }
                  />
                )}
                {canEdit && row.removable === true && (
                  <ConfirmButton
                    label="Remove"
                    variant="ghost"
                    disabled={saving || row.save_in_progress === true}
                    onConfirm={() => mutate(base + '/housing/remove', { space_key: row.space_key })}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      />
      {open && (
        <PaginatedRecords
          title="Placed furniture"
          path={base + '/housing/' + encodeURIComponent(open)}
          revision={revision}
          load={api}
          emptyText="Nothing placed."
          renderItems={(items) => (
            <div className="grid gap-2 sm:grid-cols-2">
              {items.map((row, index) => (
                <ItemTile key={index} row={row} />
              ))}
            </div>
          )}
        />
      )}
    </div>
  );
}

type Section = {
  base: string;
  api: Api;
  mutate: Mutate;
  saving: boolean;
  revision: number;
  canEdit: boolean;
};

export function CharacterPanel({
  accountId,
  api,
  mutate,
  saving,
  revision,
  canEdit,
  compact = false,
}: {
  accountId: string;
  api: Api;
  mutate: Mutate;
  saving: boolean;
  revision: number;
  canEdit: boolean;
  compact?: boolean;
}) {
  const base = 'users/' + encodeURIComponent(accountId) + '/character';
  const [data, setData] = useState<Row | null>(null),
    [error, setError] = useState(''),
    [position, setPosition] = useState<Row | null>(null);
  useEffect(() => {
    let current = true;
    api(base)
      .then((value) => current && setData(value))
      .catch((failure) => current && setError(failure.message));
    if (!compact)
      api(base + '/position')
        .then((value) => current && setPosition(value))
        .catch(() => {});
    return () => {
      current = false;
    };
  }, [api, base, revision, compact]);
  const section: Section = { base, api, mutate, saving, revision, canEdit };
  const outfitCard = (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          Wearing now
          {compact && (
            <a
              href={playerHref(accountId, 'character')}
              className="ml-auto text-xs font-normal text-muted-foreground hover:underline"
            >
              Character →
            </a>
          )}
        </CardTitle>
        {!compact && typeof data?.live_changes_note === 'string' && (
          <CardDescription>{String(data.live_changes_note)}</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : !data ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <Outfit data={data} />
        )}
      </CardContent>
    </Card>
  );
  if (compact) return outfitCard;
  const count = (key: string) =>
    (data?.sections as Row[] | undefined)?.find((s) => s.id === key)?.count;
  return (
    <div className="grid gap-3">
      {outfitCard}
      <Tabs defaultValue="presets" className="gap-3">
        <TabsList className="h-auto w-full flex-wrap justify-start gap-1 p-1">
          {[
            ['presets', 'Outfits'],
            ['preferences', 'Settings'],
            ['social', 'Friends'],
            ['housing', 'Apartments'],
            ['position', 'Location'],
            ['consumables', 'Consumables'],
          ].map(([value, label]) => (
            <TabsTrigger key={value} value={value} className="flex-none px-3 text-xs">
              {label}
              {typeof count(value) === 'number' && (
                <span className="ml-1 text-muted-foreground">{String(count(value))}</span>
              )}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="presets">
          <Presets {...section} />
        </TabsContent>
        <TabsContent value="preferences">
          <Preferences {...section} />
        </TabsContent>
        <TabsContent value="social">
          <Social {...section} />
        </TabsContent>
        <TabsContent value="housing">
          <Housing {...section} />
        </TabsContent>
        <TabsContent value="position">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Last known location</CardTitle>
              <CardDescription>
                Reset if a player is stuck; they spawn at the default point next login.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap items-center gap-3">
              {position?.position ? (
                <span className="font-mono text-xs">
                  {['x', 'y', 'z']
                    .map((axis) => axis + ' ' + Number((position.position as Row)[axis]).toFixed(1))
                    .join('  ')}
                </span>
              ) : (
                <span className="text-sm text-muted-foreground">Default spawn</span>
              )}
              <span className="text-xs text-muted-foreground">
                {String(position?.source || '')}{' '}
                {position?.updated_at ? '· ' + relative(position.updated_at) : ''}
              </span>
              {canEdit && position?.saved === true && (
                <ConfirmButton
                  label="Reset to spawn"
                  disabled={saving}
                  onConfirm={() => mutate(base + '/position/reset', {})}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="consumables">
          <PaginatedRecords
            title="Consumables"
            path={base + '/consumables'}
            revision={revision}
            load={api}
            columns={['label', 'units', 'prop_use_count', 'updated_at']}
            emptyText="No consumables."
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Remove an owned item (also unequips it from saved outfits). */
export function RevokeItem({
  row,
  accountId,
  mutate,
  saving,
}: {
  row: Row;
  accountId: string;
  mutate: Mutate;
  saving: boolean;
}) {
  if (row.revocable === false || row.starter === true) return null;
  return (
    <ConfirmButton
      label="Remove"
      variant="ghost"
      disabled={saving}
      onConfirm={() =>
        mutate('users/' + encodeURIComponent(accountId) + '/character/items/revoke', {
          kind: row.kind,
          item_id: row.item_id,
          ...(row.kind === 'wardrobe' ? { gender: row.gender, category: row.category } : {}),
        })
      }
    />
  );
}
