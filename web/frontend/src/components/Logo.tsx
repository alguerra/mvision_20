import { Eye } from "lucide-react"

interface LogoProps {
  size?: 'sm' | 'md' | 'lg';
  showText?: boolean;
}

export function Logo({ size = 'md', showText = true }: LogoProps) {
  const sizeClasses = {
    sm: 'h-6 w-6',
    md: 'h-10 w-10',
    lg: 'h-16 w-16',
  };

  const textClasses = {
    sm: 'text-lg',
    md: 'text-2xl',
    lg: 'text-4xl',
  };

  return (
    <div className="flex items-center gap-3">
      <div className={`${sizeClasses[size]} text-primary`}>
        <Eye className="w-full h-full" />
      </div>
      {showText && (
        <span className={`font-bold ${textClasses[size]} tracking-tight`}>
          MVISION
        </span>
      )}
    </div>
  );
}
