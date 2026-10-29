import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

export function FormSelect({
  id,
  name,
  value,
  defaultValue,
  options,
  onValueChange,
  disabled,
  required,
  className = '',
}: {
  id: string;
  name?: string;
  value?: string;
  defaultValue?: string;
  options: (string | { value: string; label: string })[];
  onValueChange?: (value: string) => void;
  disabled?: boolean;
  required?: boolean;
  className?: string;
}) {
  return (
    <Select
      name={name}
      value={value}
      defaultValue={defaultValue}
      onValueChange={onValueChange}
      disabled={disabled}
      required={required}
    >
      <SelectTrigger id={id} className={'min-h-11 w-full min-w-0 ' + className}>
        <SelectValue placeholder="Choose an option" />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => {
          const item =
            typeof option === 'string'
              ? {
                  value: option,
                  label: option === 'np' ? 'Nebula Points' : option.replaceAll('_', ' '),
                }
              : option;
          return (
            <SelectItem key={item.value} value={item.value} className="min-h-11 capitalize">
              {item.label}
            </SelectItem>
          );
        })}
      </SelectContent>
    </Select>
  );
}
