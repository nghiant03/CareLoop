import { useState } from 'react';
import { api, label, type Food, type FoodBody } from '../api';
import {
  Details,
  Feedback,
  Field,
  FoodPicker,
  Form,
  Panel,
} from '../components/shared';
import { decision, useSession, useTask } from '../state';

export default function Foods() {
  const [selected, setSelected] = useState<Food[]>([]);
  return (
    <>
      <Panel title="Food catalogue">
        <FoodPicker
          multiple={false}
          selected={selected}
          onChange={setSelected}
        />
      </Panel>
      {selected[0] && (
        <FoodEditor
          key={`${selected[0].id}-${selected[0].latest_revision}`}
          food={selected[0]}
          onSaved={(food) => setSelected([food])}
        />
      )}
    </>
  );
}

function FoodEditor({
  food,
  onSaved,
}: {
  food: Food;
  onSaved: (f: Food) => void;
}) {
  const { actor } = useSession();
  const task = useTask();
  const [body, setBody] = useState<FoodBody>(food.body);
  const [reason, setReason] = useState('');
  const update = (patch: Partial<FoodBody>) =>
    setBody((value) => ({ ...value, ...patch }));
  return (
    <Panel title={`${food.body.name} · revision ${food.latest_revision}`}>
      <Feedback task={task} />
      {!!food.body.import_warnings?.length && (
        <ul className="notice notice-warn mb-4">
          {food.body.import_warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <p className="text-ink-3 mb-4">
        Nutrients are per 100 {body.basis}. Planning uses recorded source
        portions. Ingredient and allergen classifications need supporting
        evidence.
      </p>
      <Form
        busy={task.busy || actor.role !== 'reviewer'}
        onSubmit={() =>
          void task.run(
            async () =>
              onSaved(
                await api<Food>(`/foods/${food.id}/revisions`, {
                  ...decision(actor, reason),
                  expected_revision: food.latest_revision,
                  body: { ...body, review_note: reason },
                }),
              ),
            'Food revision saved. Referencing plans have been flagged for review.',
          )
        }
      >
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Food name">
            <input
              className="field"
              required
              value={body.name}
              onChange={(e) => update({ name: e.target.value })}
            />
          </Field>
          <Field label="Category">
            <input
              className="field"
              required
              value={body.category}
              onChange={(e) => update({ category: e.target.value })}
            />
          </Field>
        </div>
        <section aria-label="Source portions">
          <h3 className="font-semibold mb-2">Source portions</h3>
          <p className="text-sm text-ink-3 mb-2">
            These recorded quantities are available for planning at any meal.
          </p>
          {!body.portions.length && (
            <p className="notice">
              No source portion with a recorded quantity is available.
            </p>
          )}
          <ul>
            {body.portions.map((portion) => (
              <li key={portion.id} className="py-2">
                <span>
                  {portion.label} · {portion.grams ?? portion.millilitres}{' '}
                  {body.basis} edible
                </span>
              </li>
            ))}
          </ul>
        </section>
        <div className="grid sm:grid-cols-3 gap-4">
          {(['vegetarian', 'contains_egg', 'contains_dairy'] as const).map(
            (key) => (
              <Field key={key} label={label(key)}>
                <select
                  className="field"
                  value={body[key] == null ? '' : String(body[key])}
                  onChange={(e) =>
                    update({
                      [key]:
                        e.target.value === ''
                          ? null
                          : e.target.value === 'true',
                    })
                  }
                >
                  <option value="">Unknown</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </Field>
            ),
          )}
        </div>
        <details>
          <summary className="cursor-pointer font-semibold text-line">
            Allergen classifications
          </summary>
          <div className="grid sm:grid-cols-3 gap-3 mt-3">
            {[
              'egg',
              'milk',
              'peanut',
              'tree_nut',
              'soy',
              'wheat',
              'fish',
              'shellfish',
              'sesame',
              'gluten',
              'sulphite',
              'celery',
              'mustard',
              'lupin',
              'mollusc',
            ].map((key) => (
              <Field key={key} label={label(key)}>
                <select
                  className="field"
                  value={body.allergen_status[key] ?? 'unknown'}
                  onChange={(e) =>
                    update({
                      allergen_status: {
                        ...body.allergen_status,
                        [key]: e.target.value,
                      },
                    })
                  }
                >
                  <option value="unknown">Unknown</option>
                  <option value="present">Present</option>
                  <option value="absent">Absent (reviewed)</option>
                </select>
              </Field>
            ))}
          </div>
        </details>
        <details>
          <summary className="cursor-pointer font-semibold text-line">
            Correct nutrient values
          </summary>
          <div className="grid sm:grid-cols-3 gap-3 mt-3">
            {Object.entries(body.nutrients).map(([key, value]) => (
              <Field
                key={key}
                label={`${label(key)} (${key === 'energy' ? 'kcal' : ['sodium', 'potassium', 'phosphorus'].includes(key) ? 'mg' : 'g'})`}
              >
                <input
                  className="field"
                  type="number"
                  min="0"
                  max="1000000"
                  step="any"
                  placeholder="Unknown"
                  value={value ?? ''}
                  onChange={(e) =>
                    update({
                      nutrients: {
                        ...body.nutrients,
                        [key]:
                          e.target.value === '' ? null : Number(e.target.value),
                      },
                    })
                  }
                />
              </Field>
            ))}
          </div>
        </details>
        <Field label="Review note and correction reason">
          <textarea
            className="field"
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <button className="btn-primary">Save reviewed food revision</button>
      </Form>
      <Details title="Source provenance" value={food.body.provenance} />
      {actor.role !== 'reviewer' && (
        <p className="text-sm text-ink-3">
          Switch to the reviewer demo role to correct or annotate foods.
        </p>
      )}
    </Panel>
  );
}
