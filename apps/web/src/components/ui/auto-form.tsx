"use client";

// DOCUMENTATION
// AutoForm is a React component that automatically creates a @shadcn/ui form based on a zod schema.
// https://github.com/vantezzen/auto-form/tree/main
import React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ControllerRenderProps,
  DefaultValues,
  FieldPath,
  FieldValues,
  useForm,
} from "react-hook-form";
import { z } from "zod";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "./accordion";
import { Button } from "./button";
import { Checkbox } from "./checkbox";
import { DatePicker } from "./date-picker";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "./form";
import { Input } from "./input";
import { RadioGroup, RadioGroupItem } from "./radio-group";
import { Switch } from "./switch";
import { Textarea } from "./textarea";

/**
 * Beautify a camelCase string.
 * e.g. "myString" -> "My String"
 */
function beautifyObjectName(string: string) {
  let output = string.replace(/([A-Z])/g, " $1");
  output = output.charAt(0).toUpperCase() + output.slice(1);
  return output;
}

/**
 * Get the lowest level Zod type.
 * This will unpack optionals, refinements, etc.
 */
type WrappedZodDefinition = z.ZodTypeDef & {
  defaultValue?: () => unknown;
  innerType?: z.ZodTypeAny;
  schema?: z.ZodTypeAny;
  typeName?: z.ZodFirstPartyTypeKind;
};

function getBaseSchema(schema: z.ZodTypeAny): z.ZodTypeAny {
  const definition = schema._def as WrappedZodDefinition;
  if (definition.innerType) {
    return getBaseSchema(definition.innerType);
  }
  if (definition.schema) {
    return getBaseSchema(definition.schema);
  }
  return schema;
}

/**
 * Get the type name of the lowest level Zod type.
 * This will unpack optionals, refinements, etc.
 */
function getBaseType(schema: z.ZodTypeAny): string {
  return getBaseSchema(schema)._def.typeName;
}

/**
 * Search for a "ZodDefult" in the Zod stack and return its value.
 */
function getDefaultValueInZodStack(schema: z.ZodTypeAny): unknown {
  const definition = schema._def as WrappedZodDefinition;

  if (definition.typeName === "ZodDefault" && definition.defaultValue) {
    return definition.defaultValue();
  }

  if (definition.innerType) {
    return getDefaultValueInZodStack(definition.innerType);
  }
  if (definition.schema) {
    return getDefaultValueInZodStack(definition.schema);
  }
  return undefined;
}

/**
 * Get all default values from a Zod schema.
 */
function getDefaultValues<Schema extends z.AnyZodObject>(schema: Schema) {
  const { shape } = schema;
  type DefaultValuesType = DefaultValues<Partial<z.infer<Schema>>>;
  const defaultValues: Record<string, unknown> = {};

  for (const key of Object.keys(shape)) {
    const item = shape[key] as z.ZodTypeAny;

    if (getBaseType(item) === "ZodObject") {
      const defaultItems = getDefaultValues(
        getBaseSchema(item) as z.AnyZodObject,
      );
      for (const defaultItemKey of Object.keys(defaultItems)) {
        const pathKey = `${key}.${defaultItemKey}`;
        defaultValues[pathKey] = defaultItems[defaultItemKey];
      }
    } else {
      const defaultValue = getDefaultValueInZodStack(item);
      if (defaultValue !== undefined) {
        defaultValues[key] = defaultValue;
      }
    }
  }

  return defaultValues as DefaultValuesType;
}

function getObjectFormSchema(schema: ZodObjectOrWrapped): z.AnyZodObject {
  if (schema instanceof z.ZodEffects) {
    return getObjectFormSchema(schema.innerType());
  }
  return schema;
}

/**
 * Convert a Zod schema to HTML input props to give direct feedback to the user.
 * Once submitted, the schema will be validated completely.
 */
function zodToHtmlInputProps(
  schema: z.ZodTypeAny,
): React.InputHTMLAttributes<HTMLInputElement> {
  const definition = schema._def as WrappedZodDefinition;
  if (
    (definition.typeName === "ZodOptional" ||
      definition.typeName === "ZodNullable") &&
    definition.innerType
  ) {
    return {
      ...zodToHtmlInputProps(definition.innerType),
      required: false,
    };
  }

  const inputProps: React.InputHTMLAttributes<HTMLInputElement> = {
    required: true,
  };
  const baseSchema = getBaseSchema(schema);

  if (
    !(baseSchema instanceof z.ZodString || baseSchema instanceof z.ZodNumber)
  ) {
    return {};
  }

  for (const check of baseSchema._def.checks) {
    if (check.kind === "min") {
      if (baseSchema instanceof z.ZodString) {
        inputProps.minLength = check.value;
      } else {
        inputProps.min = check.value;
      }
    }
    if (check.kind === "max") {
      if (baseSchema instanceof z.ZodString) {
        inputProps.maxLength = check.value;
      } else {
        inputProps.max = check.value;
      }
    }
  }

  return inputProps;
}

function getEnumValues(schema: z.ZodTypeAny): string[] {
  const baseSchema = getBaseSchema(schema);

  if (baseSchema instanceof z.ZodEnum) {
    return [...baseSchema.options];
  }

  if (baseSchema instanceof z.ZodNativeEnum) {
    return Object.values(baseSchema.enum).filter(
      (value): value is string => typeof value === "string",
    );
  }

  return [];
}

export type FieldConfigItem = {
  description?: React.ReactNode;
  inputProps?: React.InputHTMLAttributes<HTMLInputElement>;
  fieldType?:
    | keyof typeof INPUT_COMPONENTS
    | React.FC<AutoFormInputComponentProps>;

  renderParent?: (props: {
    children: React.ReactNode;
  }) => React.ReactElement | null;
};

export type FieldConfig<SchemaType extends Record<string, unknown>> = {
  // If SchemaType.key is an object, create a nested FieldConfig, otherwise FieldConfigItem
  [Key in keyof SchemaType]?: SchemaType[Key] extends Record<string, unknown>
    ? FieldConfig<SchemaType[Key]>
    : FieldConfigItem;
};

/**
 * A FormInput component can handle a specific Zod type (e.g. "ZodBoolean")
 */
export type AutoFormInputComponentProps = {
  zodInputProps: React.InputHTMLAttributes<HTMLInputElement>;
  field: ControllerRenderProps<FieldValues, FieldPath<FieldValues>>;
  fieldConfigItem: FieldConfigItem;
  label: string;
  isRequired: boolean;
  fieldProps: Record<string, unknown>;
  zodItem: z.ZodTypeAny;
};

function AutoFormInput({
  label,
  isRequired,
  fieldConfigItem,
  fieldProps,
}: AutoFormInputComponentProps) {
  return (
    <FormItem>
      <FormLabel>
        {label}
        {isRequired && <span className="text-destructive"> *</span>}
      </FormLabel>
      <FormControl>
        <Input
          type="text"
          {...(fieldProps as React.ComponentProps<typeof Input>)}
        />
      </FormControl>
      {fieldConfigItem.description && (
        <FormDescription>{fieldConfigItem.description}</FormDescription>
      )}
      <FormMessage />
    </FormItem>
  );
}

function AutoFormNumber({ fieldProps, ...props }: AutoFormInputComponentProps) {
  return (
    <AutoFormInput
      fieldProps={{
        type: "number",
        ...fieldProps,
      }}
      {...props}
    />
  );
}

function AutoFormTextarea({
  label,
  isRequired,
  fieldConfigItem,
  fieldProps,
}: AutoFormInputComponentProps) {
  return (
    <FormItem>
      <FormLabel>
        {label}
        {isRequired && <span className="text-destructive"> *</span>}
      </FormLabel>
      <FormControl>
        <Textarea {...(fieldProps as React.ComponentProps<typeof Textarea>)} />
      </FormControl>
      {fieldConfigItem.description && (
        <FormDescription>{fieldConfigItem.description}</FormDescription>
      )}
      <FormMessage />
    </FormItem>
  );
}

function AutoFormCheckbox({
  label,
  isRequired,
  field,
  fieldConfigItem,
  fieldProps,
}: AutoFormInputComponentProps) {
  return (
    <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
      <FormControl>
        <Checkbox
          checked={field.value}
          onCheckedChange={field.onChange}
          {...(fieldProps as React.ComponentProps<typeof Checkbox>)}
        />
      </FormControl>
      <div className="space-y-1 leading-none">
        <FormLabel>
          {label}
          {isRequired && <span className="text-destructive"> *</span>}
        </FormLabel>
        {fieldConfigItem.description && (
          <FormDescription>{fieldConfigItem.description}</FormDescription>
        )}
      </div>
    </FormItem>
  );
}

function AutoFormSwitch({
  label,
  isRequired,
  field,
  fieldConfigItem,
  fieldProps,
}: AutoFormInputComponentProps) {
  return (
    <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
      <FormControl>
        <Switch
          checked={field.value}
          onCheckedChange={field.onChange}
          {...(fieldProps as React.ComponentProps<typeof Switch>)}
        />
      </FormControl>
      <div className="space-y-1 leading-none">
        <FormLabel>
          {label}
          {isRequired && <span className="text-destructive"> *</span>}
        </FormLabel>
        {fieldConfigItem.description && (
          <FormDescription>{fieldConfigItem.description}</FormDescription>
        )}
      </div>
    </FormItem>
  );
}

function AutoFormRadioGroup({
  label,
  isRequired,
  field,
  zodItem,
  fieldProps,
}: AutoFormInputComponentProps) {
  const values = getEnumValues(zodItem);

  return (
    <FormItem className="space-y-3">
      <FormLabel>
        {label}
        {isRequired && <span className="text-destructive"> *</span>}
      </FormLabel>
      <FormControl>
        <RadioGroup
          onValueChange={field.onChange}
          defaultValue={field.value}
          className="flex flex-col space-y-1"
          {...(fieldProps as React.ComponentProps<typeof RadioGroup>)}
        >
          {values.map((value) => (
            <FormItem
              className="flex items-center space-x-3 space-y-0"
              key={value}
            >
              <FormControl>
                <RadioGroupItem value={value} />
              </FormControl>
              <FormLabel className="font-normal">{value}</FormLabel>
            </FormItem>
          ))}
        </RadioGroup>
      </FormControl>
      <FormMessage />
    </FormItem>
  );
}

function AutoFormDate({
  label,
  isRequired,
  field,
  fieldConfigItem,
  fieldProps,
}: AutoFormInputComponentProps) {
  return (
    <FormItem>
      <FormLabel>
        {label}
        {isRequired && <span className="text-destructive"> *</span>}
      </FormLabel>
      <FormControl>
        <DatePicker
          {...(fieldProps as unknown as Partial<
            React.ComponentProps<typeof DatePicker>
          >)}
          date={field.value}
          setDate={field.onChange}
        />
      </FormControl>
      {fieldConfigItem.description && (
        <FormDescription>{fieldConfigItem.description}</FormDescription>
      )}
      <FormMessage />
    </FormItem>
  );
}

function AutoFormEnum({
  label,
  isRequired,
  field,
  fieldConfigItem,
  zodItem,
}: AutoFormInputComponentProps) {
  const values = getEnumValues(zodItem);

  return (
    <FormItem>
      <FormLabel>
        {label}
        {isRequired && <span className="text-destructive"> *</span>}
      </FormLabel>
      <FormControl>
        <Select onValueChange={field.onChange} defaultValue={field.value}>
          <SelectTrigger>
            <SelectValue className="w-full">
              {field.value ?? "Select an option"}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {values.map((value) => (
              <SelectItem value={value} key={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormControl>
      {fieldConfigItem.description && (
        <FormDescription>{fieldConfigItem.description}</FormDescription>
      )}
      <FormMessage />
    </FormItem>
  );
}

const INPUT_COMPONENTS = {
  checkbox: AutoFormCheckbox,
  date: AutoFormDate,
  select: AutoFormEnum,
  radio: AutoFormRadioGroup,
  switch: AutoFormSwitch,
  textarea: AutoFormTextarea,
  number: AutoFormNumber,
  fallback: AutoFormInput,
};

/**
 * Define handlers for specific Zod types.
 * You can expand this object to support more types.
 */
const DEFAULT_ZOD_HANDLERS: {
  [key: string]: keyof typeof INPUT_COMPONENTS;
} = {
  ZodBoolean: "checkbox",
  ZodDate: "date",
  ZodEnum: "select",
  ZodNativeEnum: "select",
  ZodNumber: "number",
};

function DefaultParent({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function AutoFormObject<SchemaType extends z.AnyZodObject>({
  schema,
  form,
  fieldConfig,
  path = [],
}: {
  schema: SchemaType;
  form: ReturnType<typeof useForm>;
  fieldConfig?: FieldConfig<z.infer<SchemaType>>;
  path?: string[];
}) {
  const { shape } = schema;

  return (
    <Accordion type="multiple" className="space-y-5">
      {Object.keys(shape).map((name) => {
        const item = shape[name] as z.ZodTypeAny;
        const zodBaseType = getBaseType(item);
        const itemName = item._def.description ?? beautifyObjectName(name);
        const key = `${path.join(".")}.${name}`;

        if (zodBaseType === "ZodObject") {
          return (
            <AccordionItem value={name} key={key}>
              <AccordionTrigger>{itemName}</AccordionTrigger>
              <AccordionContent className="p-2">
                <AutoFormObject
                  schema={getBaseSchema(item) as z.AnyZodObject}
                  form={form}
                  fieldConfig={
                    (fieldConfig?.[name] ?? {}) as FieldConfig<
                      z.infer<typeof item>
                    >
                  }
                  path={[...path, name]}
                />
              </AccordionContent>
            </AccordionItem>
          );
        }

        const fieldConfigItem: FieldConfigItem = fieldConfig?.[name] ?? {};
        const zodInputProps = zodToHtmlInputProps(item);
        const isRequired =
          zodInputProps.required ??
          fieldConfigItem.inputProps?.required ??
          false;

        return (
          <FormField
            control={form.control}
            name={key}
            key={key}
            render={({ field }) => {
              const inputType =
                fieldConfigItem.fieldType ??
                DEFAULT_ZOD_HANDLERS[zodBaseType] ??
                "fallback";

              const InputComponent =
                typeof inputType === "function"
                  ? inputType
                  : INPUT_COMPONENTS[inputType];
              const ParentElement =
                fieldConfigItem.renderParent ?? DefaultParent;

              return (
                <ParentElement key={`${key}.parent`}>
                  <InputComponent
                    zodInputProps={zodInputProps}
                    field={field}
                    fieldConfigItem={fieldConfigItem}
                    label={itemName}
                    isRequired={isRequired}
                    zodItem={item}
                    fieldProps={{
                      ...zodInputProps,
                      ...field,
                      ...fieldConfigItem.inputProps,
                      value: !fieldConfigItem.inputProps?.defaultValue
                        ? field.value ?? ""
                        : undefined,
                    }}
                  />
                </ParentElement>
              );
            }}
          />
        );
      })}
    </Accordion>
  );
}

export function AutoFormSubmit({ children }: { children?: React.ReactNode }) {
  return <Button type="submit">{children ?? "Submit"}</Button>;
}

// TODO: This should support recursive ZodEffects but TypeScript doesn't allow circular type definitions.
type ZodObjectOrWrapped = z.AnyZodObject | z.ZodEffects<z.AnyZodObject>;

function AutoForm<SchemaType extends ZodObjectOrWrapped>({
  formSchema,
  values: valuesProp,
  onValuesChange: onValuesChangeProp,
  onSubmit: onSubmitProp,
  fieldConfig,
  children,
  className,
}: {
  formSchema: SchemaType;
  values?: Partial<z.infer<SchemaType>>;
  onValuesChange?: (values: Partial<z.infer<SchemaType>>) => void;
  onSubmit?: (values: z.infer<SchemaType>) => void;
  fieldConfig?: FieldConfig<z.infer<SchemaType>>;
  children?: React.ReactNode;
  className?: string;
}) {
  const objectFormSchema = getObjectFormSchema(formSchema);
  const defaultValues: DefaultValues<z.infer<typeof objectFormSchema>> =
    getDefaultValues(objectFormSchema);

  const form = useForm<z.infer<typeof objectFormSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues,
    values: valuesProp,
  });

  function onSubmit(values: z.infer<typeof formSchema>) {
    const parsedValues = formSchema.safeParse(values);
    if (parsedValues.success) {
      onSubmitProp?.(parsedValues.data);
    }
  }

  return (
    <Form {...form}>
      <form
        onSubmit={(e) => {
          form.handleSubmit(onSubmit)(e);
        }}
        onChange={() => {
          const values = form.getValues();
          const parsedValues = formSchema.safeParse(values);
          if (parsedValues.success) {
            onValuesChangeProp?.(parsedValues.data);
          }
        }}
        className={cn("space-y-5", className)}
      >
        <AutoFormObject
          schema={objectFormSchema}
          form={form}
          fieldConfig={fieldConfig}
        />

        {children}
      </form>
    </Form>
  );
}

export default AutoForm;
